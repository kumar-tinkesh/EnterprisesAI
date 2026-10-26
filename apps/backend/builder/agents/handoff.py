"""Handing a task to another agent: sub-agents as tools.

An agent's ``config.sub_agent_ids`` names up to five other standalone agents
in the tenant. Each becomes a function ``ask_<name>(task)``; calling it runs
that agent on the task, inside the same run, and its answer comes back as the
tool result (``builder.agents.runtime``).

* **Frozen like everything else.** A run's definition carries a snapshot of
  every sub-agent its agents may call (``definition["sub_agents"]``), taken
  when the run is created, so edits made while it runs don't change it.
* **One level.** A sub-agent runs without sub-agents of its own, so agents
  can't call each other in circles.
* **Same person, same rules.** It runs as the run's user with their
  connections; for asking before tools run, the stricter of the two agents'
  policies applies. Its tool calls go through the same ledger and approvals.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from builder.models import BuilderAgent

PREFIX = "ask_"
_MAX_NAME = 64


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]+", "_", text)).strip("_").lower() or "agent"


def _configs(definition: dict) -> list[dict]:
    agents = [definition["agent"]] if "agent" in definition else list((definition.get("agents") or {}).values())
    return [a.get("config") or {} for a in agents]


async def freeze_sub_agents(db: AsyncSession, tenant_id: str, definition: dict) -> dict:
    """``definition`` plus a snapshot of every sub-agent its agents name (once)."""
    if "sub_agents" in definition:
        return definition
    ids = list(dict.fromkeys(i for c in _configs(definition) for i in c.get("sub_agent_ids") or []))
    if not ids:
        return definition
    from builder.runs.service import agent_snapshot

    rows = (
        await db.execute(
            select(BuilderAgent).where(
                BuilderAgent.id.in_(ids), BuilderAgent.tenant_id == tenant_id, BuilderAgent.workflow_id.is_(None)
            )
        )
    ).scalars().all()
    return {**definition, "sub_agents": {a.id: agent_snapshot(a) for a in rows}}


def sub_agent_functions(sub_agent_ids: list[str], sub_agents: dict[str, dict], taken: set[str]) -> dict[str, dict]:
    """{function name: sub-agent snapshot} for the ones this agent may call."""
    out: dict[str, dict] = {}
    for sid in sub_agent_ids:
        sub = sub_agents.get(sid)
        if sub is None:
            continue
        base = (PREFIX + _slug(sub.get("name") or "agent"))[:_MAX_NAME]
        name, n = base, 2
        while name in taken or name in out:
            suffix = f"_{n}"
            name, n = base[: _MAX_NAME - len(suffix)] + suffix, n + 1
        out[name] = sub
    return out


def handoff_definition(name: str, sub: dict) -> dict:
    who = f"{sub.get('name') or 'Another agent'}, {sub.get('role') or 'an agent'}"
    return {
        "name": name,
        "description": (
            f"Hand a task to {who}. Its goal: {sub.get('goal') or ''}. It works on the task with its own tools and "
            "knowledge and returns its answer. Give it everything it needs in the task: it can't see this conversation."
        ).strip(),
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string", "description": "What it should do, with all the details it needs"}},
            "required": ["task"],
        },
    }


def team_section(subs: dict[str, dict]) -> str:
    lines = "\n".join(f"- {fn}: {s.get('name')} ({s.get('role')}) — {s.get('goal')}" for fn, s in subs.items())
    return (
        "You can hand tasks to these agents with their tools when their goal fits a part of the work better than "
        f"you do; combine what they return into your answer:\n{lines}"
    )


__all__ = ["freeze_sub_agents", "handoff_definition", "sub_agent_functions", "team_section"]
