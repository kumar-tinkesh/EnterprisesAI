"""Version history for agents and workflows: record every save, say what
changed, and bring an earlier version back.

* ``record_version`` — called right after a save (same transaction): the full
  definition at its new version number, with a one-line summary of what
  changed since the previous version.
* ``ensure_baseline`` — called before an edit: definitions that existed before
  version history did get their current state recorded first, so the very
  first edit can be undone too.
* ``restore_agent`` / ``restore_workflow`` — apply an earlier snapshot as a new
  save (version + 1, "Restored from vN"); history never gets rewritten. A
  workflow restore also brings back the workflow's own agents as they were,
  re-syncs its schedule, and is refused (with the problems) if the old
  version points at things that no longer exist.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.agents.config import AgentConfig
from builder.config import get_builder_settings
from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode
from builder.graph.validation import GraphProblem
from builder.models import BuilderAgent, BuilderVersion, BuilderWorkflow
from builder.schedules.service import sync_workflow_schedules
from builder.services.references import agent_config_problems, check_workflow

AGENT_FIELDS = ("name", "role", "goal", "instructions", "llm_provider", "llm_model", "config")
WORKFLOW_FIELDS = ("name", "description", "nodes", "edges", "config")

_STEP_TITLES = {
    "input": "Input", "manual_trigger": "Manual trigger", "schedule_trigger": "Schedule", "agent": "Agent",
    "tool": "Tool", "condition": "Condition", "join": "Join", "human_approval": "Approval", "output": "Output",
}


class RestoreError(Exception):
    def __init__(self, message: str, problems: list[GraphProblem] | None = None):
        super().__init__(message)
        self.message, self.problems = message, problems or []


# ── snapshots ───────────────────────────────────────────────────────────────


def agent_fields(agent: BuilderAgent) -> dict:
    return {f: (getattr(agent, f) or ({} if f == "config" else "")) for f in AGENT_FIELDS}


async def workflow_fields(db: AsyncSession, workflow: BuilderWorkflow) -> dict:
    own = (await db.execute(select(BuilderAgent).where(BuilderAgent.workflow_id == workflow.id))).scalars().all()
    snap: dict[str, Any] = {f: (getattr(workflow, f) or ([] if f in ("nodes", "edges") else {} if f == "config" else "")) for f in WORKFLOW_FIELDS}
    snap["agents"] = {a.id: {**agent_fields(a), "owner_id": a.owner_id} for a in own}
    return snap


def _target(kind: str, target_id: str):
    return BuilderVersion.agent_id == target_id if kind == "agent" else BuilderVersion.workflow_id == target_id


async def latest_version(db: AsyncSession, kind: str, target_id: str) -> BuilderVersion | None:
    return (
        await db.execute(select(BuilderVersion).where(_target(kind, target_id)).order_by(BuilderVersion.version.desc()).limit(1))
    ).scalars().first()


async def record_version(
    db: AsyncSession, kind: str, target: BuilderAgent | BuilderWorkflow, *, author_id: str | None, note: str
) -> BuilderVersion:
    """Record ``target`` as it is now (call after the save's changes, before commit)."""
    await db.flush()
    snap = agent_fields(target) if kind == "agent" else await workflow_fields(db, target)
    prev = await latest_version(db, kind, target.id)
    if prev is not None and prev.version >= target.version:
        # Same version number already recorded (nothing was bumped): refresh it.
        prev.snapshot, prev.note = snap, note
        return prev
    summary = ""
    if prev is not None:
        summary = summarize_agent(prev.snapshot, snap) if kind == "agent" else summarize_workflow(prev.snapshot, snap)
    row = BuilderVersion(
        tenant_id=target.tenant_id, kind=kind, version=target.version, snapshot=snap, note=note[:255],
        summary=summary, author_id=author_id,
        **({"agent_id": target.id} if kind == "agent" else {"workflow_id": target.id}),
    )
    db.add(row)
    await db.flush()  # sessions here don't autoflush: count the new row too
    await _prune(db, kind, target.id)
    return row


async def ensure_baseline(db: AsyncSession, kind: str, target: BuilderAgent | BuilderWorkflow) -> None:
    """Before changing something with no history yet, record how it is now."""
    if await latest_version(db, kind, target.id) is None:
        await record_version(db, kind, target, author_id=None, note="Before version history")


async def _prune(db: AsyncSession, kind: str, target_id: str) -> None:
    keep = get_builder_settings().BUILDER_VERSIONS_KEEP
    count = (await db.execute(select(func.count()).select_from(BuilderVersion).where(_target(kind, target_id)))).scalar_one()
    if count <= keep:
        return
    cutoff = (
        await db.execute(
            select(BuilderVersion.version).where(_target(kind, target_id)).order_by(BuilderVersion.version.desc()).offset(keep - 1).limit(1)
        )
    ).scalar_one()
    await db.execute(delete(BuilderVersion).where(_target(kind, target_id), BuilderVersion.version < cutoff))


# ── what changed ────────────────────────────────────────────────────────────


def _sentence(parts: list[str]) -> str:
    if not parts:
        return "No changes"
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


def _tool_name(tool_id: str) -> str:
    return tool_id.rsplit(":", 1)[-1]


def summarize_agent(old: dict, new: dict) -> str:
    parts: list[str] = []
    changed = [label for f, label in (("name", "name"), ("role", "role"), ("goal", "goal"), ("instructions", "instructions"))
               if (old.get(f) or "") != (new.get(f) or "")]
    if changed:
        parts.append("changed the " + " and ".join(changed) if len(changed) <= 2 else "changed the " + ", ".join(changed[:-1]) + " and " + changed[-1])
    if (old.get("llm_provider"), old.get("llm_model")) != (new.get("llm_provider"), new.get("llm_model")):
        parts.append("changed the model")
    oc, nc = old.get("config") or {}, new.get("config") or {}
    ot, nt = set(oc.get("tool_ids") or []), set(nc.get("tool_ids") or [])
    if nt - ot:
        parts.append("added " + ", ".join(sorted(_tool_name(t) for t in nt - ot)))
    if ot - nt:
        parts.append("removed " + ", ".join(sorted(_tool_name(t) for t in ot - nt)))
    ok, nk = set(oc.get("knowledge_base_ids") or []), set(nc.get("knowledge_base_ids") or [])
    if ok != nk:
        parts.append("changed its knowledge")
    rest = lambda c: {k: v for k, v in c.items() if k not in ("tool_ids", "knowledge_base_ids")}  # noqa: E731
    if rest(oc) != rest(nc):
        parts.append("changed settings")
    return _sentence(parts)


def _step_name(node: dict, agents: dict) -> str:
    if node.get("label"):
        return str(node["label"])
    if node.get("type") == "agent":
        agent = (node.get("draft_agent") or {}) or agents.get(node.get("agent_id") or "", {})
        if agent.get("name"):
            return str(agent["name"])
    return _STEP_TITLES.get(node.get("type", ""), "step")


def summarize_workflow(old: dict, new: dict) -> str:
    parts: list[str] = []
    if (old.get("name") or "") != (new.get("name") or ""):
        parts.append(f'renamed it "{new.get("name")}"')
    on = {n["id"]: n for n in old.get("nodes") or [] if n.get("id")}
    nn = {n["id"]: n for n in new.get("nodes") or [] if n.get("id")}
    oa, na = old.get("agents") or {}, new.get("agents") or {}
    added = [_step_name(nn[i], na) for i in nn if i not in on]
    removed = [_step_name(on[i], oa) for i in on if i not in nn]
    strip = lambda n: {k: v for k, v in n.items() if k != "position"}  # noqa: E731
    changed = []
    moved = False
    for i in (i for i in nn if i in on):  # canvas order, so the summary reads the same every time
        if strip(nn[i]) != strip(on[i]):
            changed.append(_step_name(nn[i], na))
        elif nn[i].get("position") != on[i].get("position"):
            moved = True
        elif nn[i].get("type") == "agent" and oa.get(nn[i].get("agent_id") or "") != na.get(nn[i].get("agent_id") or ""):
            changed.append(_step_name(nn[i], na))
    for verb, names in (("added", added), ("removed", removed), ("changed", changed)):
        if names:
            parts.append(f"{verb} " + (", ".join(names) if len(names) <= 3 else f"{len(names)} steps"))
    edge_key = lambda e: (e.get("source"), e.get("target"), e.get("condition") or None)  # noqa: E731
    if {edge_key(e) for e in old.get("edges") or []} != {edge_key(e) for e in new.get("edges") or []} and not (added or removed):
        parts.append("rewired the steps")
    if (old.get("config") or {}) != (new.get("config") or {}):
        parts.append("changed settings")
    if (old.get("description") or "") != (new.get("description") or ""):
        parts.append("changed the description")
    if not parts and moved:
        parts.append("rearranged the canvas")
    return _sentence(parts)


# ── restore ─────────────────────────────────────────────────────────────────


async def restore_agent(db: AsyncSession, agent: BuilderAgent, version: BuilderVersion, user: CurrentUser) -> None:
    snap = version.snapshot or {}
    config = AgentConfig.model_validate(snap.get("config") or {})
    problems = await agent_config_problems(db, user, config, check_connection=False)
    if problems:
        raise RestoreError(f"Version {version.version} uses things that are gone, so it can't be restored as it was.", problems)
    await ensure_baseline(db, "agent", agent)
    for field in AGENT_FIELDS:
        setattr(agent, field, config.model_dump() if field == "config" else (snap.get(field) or ""))
    agent.version += 1
    await record_version(db, "agent", agent, author_id=user.id, note=f"Restored from v{version.version}")


async def restore_workflow(db: AsyncSession, workflow: BuilderWorkflow, version: BuilderVersion, user: CurrentUser) -> None:
    snap = version.snapshot or {}
    await ensure_baseline(db, "workflow", workflow)
    # The workflow's own agents, as they were (re-created if they've been removed since).
    for agent_id, fields in (snap.get("agents") or {}).items():
        agent = await db.get(BuilderAgent, agent_id)
        if agent is None:
            agent = BuilderAgent(
                id=agent_id, tenant_id=workflow.tenant_id, owner_id=fields.get("owner_id") or workflow.owner_id,
                workflow_id=workflow.id, name="", role="", goal="",
            )
            db.add(agent)
        elif agent.workflow_id != workflow.id:
            continue  # the id now belongs to something else: leave it alone
        for field in AGENT_FIELDS:
            setattr(agent, field, fields.get(field) or ({} if field == "config" else ""))
        agent.version = (agent.version or 0) + 1
    await db.flush()

    nodes = [WorkflowNode.model_validate(n) for n in snap.get("nodes") or []]
    edges = [WorkflowEdge.model_validate(e) for e in snap.get("edges") or []]
    config = WorkflowConfig.model_validate(snap.get("config") or {})
    problems = await check_workflow(db, user, workflow_id=workflow.id, nodes=nodes, edges=edges, config=config, check_connection=False)
    if problems:
        raise RestoreError(f"Version {version.version} uses things that are gone, so it can't be restored as it was.", problems)

    workflow.name = snap.get("name") or workflow.name
    workflow.description = snap.get("description") or ""
    workflow.nodes = [n.model_dump(exclude_none=True) for n in nodes]
    workflow.edges = [e.model_dump(exclude_none=True) for e in edges]
    workflow.config = config.model_dump()
    in_use = {n.agent_id for n in nodes if n.type == "agent" and n.agent_id}
    await db.execute(delete(BuilderAgent).where(BuilderAgent.workflow_id == workflow.id, BuilderAgent.id.not_in(in_use or {""})))
    await sync_workflow_schedules(db, workflow)
    workflow.version += 1
    await record_version(db, "workflow", workflow, author_id=user.id, note=f"Restored from v{version.version}")


__all__ = [
    "RestoreError", "record_version", "ensure_baseline", "latest_version", "summarize_agent", "summarize_workflow",
    "restore_agent", "restore_workflow", "agent_fields", "workflow_fields",
]
