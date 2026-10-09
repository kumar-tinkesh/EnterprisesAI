"""Publishable keys: what a published agent/workflow runs, as whom, and how often.

* A key runs ONE agent or workflow, as the person who created it (their
  connected tools), from a pinned saved version or the latest saved one.
  Callers never see run internals — only status, the answer and its sources.
* Only a SHA-256 hash of the key is stored. Keys are long random tokens, so a
  plain hash (no salt/stretching) is the standard choice here, as for API
  keys elsewhere; the key itself is shown exactly once.
* Limits are counted from the runs themselves (per minute, per UTC day), so
  they hold across any number of API processes without shared memory.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.models import User

from builder.agents.config import AgentConfig
from builder.agents.tools import resolve_agent_tools
from builder.graph.validation import GraphProblem
from builder.models import BuilderAgent, BuilderPublicKey, BuilderRun, BuilderVersion, BuilderWorkflow
from builder.runs.db import utcnow
from builder.runs.service import agent_snapshot, create_run, workflow_definition, workflow_snapshot
from builder.services.references import tool_problems
from builder.services.tool_runtime import classify_tool

KEY_PREFIX = "eai_pk_"


class PublishError(Exception):
    def __init__(self, status_code: int, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.status_code, self.message, self.problems = status_code, message, problems or []


def new_key() -> tuple[str, str, str]:
    """-> (the key, its hash, a display prefix)."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_key(key), key[: len(KEY_PREFIX) + 4]


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ── what gets run ───────────────────────────────────────────────────────────


async def definition_for(db: AsyncSession, kind: str, target: BuilderAgent | BuilderWorkflow, version: int | None) -> tuple[dict, int]:
    """The frozen definition a key runs -> (definition, version number).
    ``version`` None = the latest saved; else that saved version's snapshot."""
    if version is None or version == target.version:
        if kind == "agent":
            return {"agent": agent_snapshot(target)}, target.version
        return await workflow_definition(db, target.tenant_id, workflow_snapshot(target)), target.version
    column = BuilderVersion.agent_id if kind == "agent" else BuilderVersion.workflow_id
    row = (await db.execute(select(BuilderVersion).where(column == target.id, BuilderVersion.version == version))).scalars().first()
    if row is None:
        raise PublishError(409, f"Version {version} is no longer kept; publish a newer one.")
    snap = row.snapshot or {}
    if kind == "agent":
        fields = {k: snap.get(k) for k in ("name", "role", "goal", "instructions", "llm_provider", "llm_model", "config")}
        return {"agent": {"id": target.id, **fields, "version": version}}, version
    workflow = {"id": target.id, "name": snap.get("name") or target.name, "nodes": snap.get("nodes") or [],
                "edges": snap.get("edges") or [], "config": snap.get("config") or {}, "version": version}
    own = {aid: {"id": aid, **{k: a.get(k) for k in ("name", "role", "goal", "instructions", "llm_provider", "llm_model", "config")}}
           for aid, a in (snap.get("agents") or {}).items()}
    return await workflow_definition(db, target.tenant_id, workflow, frozen_agents=own), version


def _agents_in(definition: dict) -> list[dict]:
    return [definition["agent"]] if "agent" in definition else list((definition.get("agents") or {}).values())


def tool_ids_in(definition: dict) -> list[str]:
    ids: list[str] = []
    for agent in _agents_in(definition):
        ids += AgentConfig.model_validate(agent.get("config") or {}).tool_ids
    for n in (definition.get("workflow") or {}).get("nodes") or []:
        if n.get("type") == "tool" and n.get("tool_id"):
            ids.append(n["tool_id"])
    return list(dict.fromkeys(ids))


async def write_tools(db: AsyncSession, definition: dict) -> list[str]:
    """"Server.tool" for every data-changing tool a caller could make it use."""
    tools = await resolve_agent_tools(db, tool_ids_in(definition))
    return sorted(f"{t.server_name}.{t.tool_name}" for t in tools if classify_tool(t.tool_name, t.annotations).risk != "read")


def input_fields(definition: dict) -> list[dict]:
    fields: list[dict] = []
    for n in (definition.get("workflow") or {}).get("nodes") or []:
        for v in n.get("variables") or []:
            fields.append({k: v.get(k) for k in ("name", "label", "type", "required", "description")})
    return fields


async def definition_problems(db: AsyncSession, user: CurrentUser, definition: dict, variables: dict) -> list[str]:
    """Can ``user`` run this frozen definition right now? (Their tool connections, required inputs.)"""
    problems: list[GraphProblem] = await tool_problems(db, user, tool_ids_in(definition), check_connection=True)
    messages = [p.message for p in problems]
    for f in input_fields(definition):
        if f.get("required") and variables.get(f["name"]) in (None, ""):
            messages.append(f'Fill in "{f.get("label") or f["name"]}".')
    return list(dict.fromkeys(messages))


# ── keys in use ─────────────────────────────────────────────────────────────


async def publisher(db: AsyncSession, key: BuilderPublicKey) -> CurrentUser:
    user = await db.get(User, key.owner_id)
    if user is None or not user.is_active or user.tenant_id != key.tenant_id:
        raise PublishError(403, "This key's publisher no longer has access, so it can't run.")
    return CurrentUser(id=user.id, email=user.email, full_name=user.full_name, role=user.role, tenant_id=user.tenant_id)


async def target_of(db: AsyncSession, key: BuilderPublicKey) -> BuilderAgent | BuilderWorkflow:
    target = await db.get(BuilderAgent, key.agent_id) if key.kind == "agent" else await db.get(BuilderWorkflow, key.workflow_id)
    if target is None or target.tenant_id != key.tenant_id:
        raise PublishError(410, "What this key published no longer exists.")
    return target


async def usage(db: AsyncSession, key_id: str, since: datetime) -> int:
    return (
        await db.execute(select(func.count()).select_from(BuilderRun).where(BuilderRun.public_key_id == key_id, BuilderRun.created_at >= since))
    ).scalar_one()


def start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def start_public_run(db: AsyncSession, key: BuilderPublicKey, *, text: str, variables: dict) -> BuilderRun:
    now = utcnow()
    if await usage(db, key.id, now - timedelta(minutes=1)) >= key.requests_per_minute:
        raise PublishError(429, f"Too many requests: this key allows {key.requests_per_minute} a minute.")
    if key.daily_quota is not None and await usage(db, key.id, start_of_day(now)) >= key.daily_quota:
        raise PublishError(429, f"This key's daily limit ({key.daily_quota} runs) is used up; it resets at 00:00 UTC.")
    user = await publisher(db, key)
    target = await target_of(db, key)
    definition, version = await definition_for(db, key.kind, target, key.version)
    if key.kind == "agent" and not text.strip():
        raise PublishError(422, "Send an input.")
    problems = await definition_problems(db, user, definition, variables)
    if problems:
        raise PublishError(422, "It can't run right now.", problems)
    key.last_used_at = now
    return await create_run(
        db, user, key.kind, target.id, definition=definition, version=version, text=text, variables=variables,
        purpose="public", public_key_id=key.id,
    )


def public_view(run: BuilderRun) -> dict:
    """What a caller may see of a run: no tool calls, no internal errors."""
    out = run.output or {}
    error = None
    if run.status == "failed":
        error = run.error if (run.error or "").startswith(("Blocked the request", "The answer was withheld")) else "It couldn't finish this request."
    elif run.status == "cancelled":
        error = "Cancelled."
    return {
        "run_id": run.id,
        "status": run.status,
        "output": run.output_text if run.status == "succeeded" else None,
        "sources": (out.get("sources") or []) if run.status == "succeeded" else [],
        "waiting_for": "approval" if run.status == "waiting" else None,
        "error": error,
        "version": run.definition_version,
    }


__all__ = [
    "PublishError", "new_key", "hash_key", "definition_for", "write_tools", "input_fields", "definition_problems",
    "publisher", "target_of", "usage", "start_of_day", "start_public_run", "public_view", "KEY_PREFIX",
]
