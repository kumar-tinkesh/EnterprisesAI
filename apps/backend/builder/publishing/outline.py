"""What a share link may show of how it works (``show_outline``), and of a run.

The outline is the steps — their names, kinds and the apps each uses — and
whether it asks before changing data. Never instructions, prompts, tool
arguments or anything a step produced: those stay the publisher's (and, on a
visitor link, the caller's own runs say only which step is where — plus the
step's notes, below).

    outline(db, kind, definition)      -> {"kind", "steps": [...], "apps": [...], "asks_before_changes"}
    run_steps(db, run, notes=False)    -> [{"id", "title", "kind", "status", "notes"?}]

**Notes.** A workflow step's answer may carry lines starting with "▸ " — a
step written to show progress ("▸ LinkedIn: 7 jobs in Hyderabad"). They are
for the person who runs it, so they're given only with ``notes`` (a run that
is the caller's own, with their own apps), at most ``MAX_NOTES`` per step.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vendor.models import VendorMCPServer

from builder.agents.config import AgentConfig
from builder.graph.schema import parse_tool_id
from builder.models import BuilderNodeRun, BuilderRun, BuilderToolCall
from builder.workflows import scheduler as S

# A step's own name when it has none; mirrors the canvas (web/lib/builder/graph.ts NODE_META).
KIND_TITLE = {
    "input": "Input", "manual_trigger": "Start", "schedule_trigger": "Schedule", "agent": "Agent", "tool": "Tool",
    "condition": "Decide", "join": "Join", "human_approval": "Approval", "output": "Answer",
}
KIND_HINT = {
    "input": "What you type", "manual_trigger": "Starts when you run it", "schedule_trigger": "Starts on a schedule",
    "condition": "Picks which way to go", "join": "Waits for the steps before it", "human_approval": "Waits for a person to approve",
    "output": "Writes the final answer",
}
NOTE_PREFIX = "▸"
MAX_NOTES = 4


def step_notes(text: str | None) -> list[str]:
    """A step answer's "▸ " lines, in order (builder.publishing.outline: Notes)."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    return [_short(ln[len(NOTE_PREFIX):].strip(), 200) for ln in lines if ln.startswith(NOTE_PREFIX) and ln[1:].strip()][:MAX_NOTES]


# How far a step got, in the words the page uses.
STEP_STATUS = {S.DONE: "succeeded", S.FAILED: "failed", S.RUNNING: "running", S.PAUSED: "waiting", S.PRUNED: "skipped"}


def _short(text: str | None, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def _server_names(db: AsyncSession, server_ids: list[str]) -> dict[str, str]:
    ids = [s for s in dict.fromkeys(server_ids) if s]
    if not ids:
        return {}
    return {s.id: s.name for s in (await db.execute(select(VendorMCPServer).where(VendorMCPServer.id.in_(ids)))).scalars()}


def _agent_server_ids(agent: dict) -> list[str]:
    config = AgentConfig.model_validate(agent.get("config") or {})
    return [p[0] for p in map(parse_tool_id, config.tool_ids) if p]


def _agent_systems(agent: dict) -> list[str]:
    """Systems it picks tools up from once connected (``tool_needs``), by name."""
    return [n.system for n in AgentConfig.model_validate(agent.get("config") or {}).tool_needs]


def _levels(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Each step's column: the longest path to it from a step nothing leads to (loops cut)."""
    ids = [n["id"] for n in nodes if n.get("id")]
    incoming: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e.get("target") in incoming and e.get("source") in incoming:
            incoming[e["target"]].append(e["source"])
    level: dict[str, int] = {}

    def depth(nid: str, seen: frozenset[str]) -> int:
        if nid in level:
            return level[nid]
        parents = [p for p in incoming.get(nid, []) if p not in seen]
        level[nid] = 0 if not parents else 1 + max(depth(p, seen | {nid}) for p in parents)
        return level[nid]

    for i in ids:
        depth(i, frozenset())
    return level


def _title(node: dict, agents: dict[str, dict], servers: dict[str, str]) -> str:
    if node.get("label"):
        return node["label"]
    kind = node.get("type") or ""
    if kind == "agent":
        agent = (node.get("draft_agent") or {}) or agents.get(node.get("agent_id") or "") or {}
        return agent.get("name") or "Agent"
    if kind == "tool":
        parsed = parse_tool_id(node.get("tool_id") or "")
        if parsed:
            return parsed[1].replace("_", " ").strip().capitalize() or "Tool"
        return node.get("need") or "Tool"
    return KIND_TITLE.get(kind, "Step")


async def outline(db: AsyncSession, kind: str, definition: dict) -> dict:
    if kind == "agent":
        agent = definition.get("agent") or {}
        team = list((definition.get("sub_agents") or {}).values())
        servers = await _server_names(db, _agent_server_ids(agent) + [s for t in team for s in _agent_server_ids(t)])
        main_apps = list(dict.fromkeys([servers[s] for s in _agent_server_ids(agent) if s in servers] + _agent_systems(agent)))
        steps = [{"id": "agent", "title": agent.get("name") or "Agent", "kind": "agent", "hint": _short(agent.get("goal")), "apps": main_apps, "level": 0}]
        for i, t in enumerate(team):
            apps = list(dict.fromkeys([servers[s] for s in _agent_server_ids(t) if s in servers] + _agent_systems(t)))
            steps.append({"id": f"team:{i}", "title": t.get("name") or "Helper", "kind": "team", "hint": _short(t.get("goal")), "apps": apps, "level": 1})
        policy = AgentConfig.model_validate(agent.get("config") or {}).approvals
        asks = policy.edit or policy.delete
    else:
        workflow = definition.get("workflow") or {}
        nodes, edges = workflow.get("nodes") or [], workflow.get("edges") or []
        agents = definition.get("agents") or {}
        by_agent = {aid: _agent_server_ids(a) for aid, a in agents.items()}
        tool_servers = [p[0] for p in (parse_tool_id(n.get("tool_id") or "") for n in nodes if n.get("type") == "tool") if p]
        servers = await _server_names(db, [s for ids in by_agent.values() for s in ids] + tool_servers)
        levels = _levels(nodes, edges)
        steps = []
        for n in nodes:
            kind_ = n.get("type") or ""
            if kind_ == "agent":
                agent = (n.get("draft_agent") or {}) or agents.get(n.get("agent_id") or "") or {}
                ids = _agent_server_ids(agent) if n.get("draft_agent") else by_agent.get(n.get("agent_id") or "", [])
                apps = list(dict.fromkeys([servers[s] for s in ids if s in servers] + _agent_systems(agent)))
                hint = _short(agent.get("goal"))
            elif kind_ == "tool":
                parsed = parse_tool_id(n.get("tool_id") or "")
                apps = [servers[parsed[0]]] if parsed and parsed[0] in servers else []
                hint = _short(n.get("need")) or "Calls one app"
            else:
                apps, hint = [], KIND_HINT.get(kind_, "")
            steps.append({"id": n.get("id"), "title": _title(n, agents, servers), "kind": kind_, "hint": hint, "apps": apps, "level": levels.get(n.get("id"), 0)})
        steps.sort(key=lambda s: s["level"])
        overrides = ((workflow.get("config") or {}).get("approval_overrides") or {})
        asks = not (overrides.get("edit") == "never" and overrides.get("delete") == "never")
    apps = list(dict.fromkeys(a for s in steps for a in s["apps"]))
    return {"kind": kind, "steps": steps, "apps": apps, "asks_before_changes": asks}


async def run_steps(db: AsyncSession, run: BuilderRun, *, notes: bool = False) -> list[dict]:
    """How far each step of a run got: a workflow's working steps (not its
    start and end), or the tools an agent called — names and status only
    (and, with ``notes``, each step's "▸ " lines)."""
    if run.kind == "workflow":
        workflow = (run.definition or {}).get("workflow") or {}
        agents = (run.definition or {}).get("agents") or {}
        state = (run.state or {}).get("nodes") or {}
        # A step's own row is written the moment it ends; the run's state only on the engine's next save, so
        # a side-by-side step that finished would still show as running.
        rows = (
            await db.execute(select(BuilderNodeRun).where(BuilderNodeRun.run_id == run.id).order_by(BuilderNodeRun.created_at))
        ).scalars().all()
        latest = {r.node_id: r for r in rows}
        out = []
        for n in workflow.get("nodes") or []:
            if n.get("type") in ("input", "manual_trigger", "schedule_trigger", "output"):
                continue
            status = STEP_STATUS.get((state.get(n.get("id")) or {}).get("status"), "pending")
            row = latest.get(n.get("id"))
            if status == "running" and row is not None and row.status in ("succeeded", "failed"):
                status = row.status
            step = {"id": n.get("id"), "title": _title(n, agents, {}), "kind": n.get("type"), "status": status}
            if notes:
                step["notes"] = step_notes(row.output_text) if row is not None and status == "succeeded" else []
            out.append(step)
        return out
    calls = (
        await db.execute(select(BuilderToolCall).where(BuilderToolCall.run_id == run.id).order_by(BuilderToolCall.created_at))
    ).scalars().all()
    done = {"succeeded": "succeeded", "failed": "failed", "declined": "skipped", "rejected": "skipped", "started": "running"}
    return [
        {"id": c.id, "title": c.tool_name.split("__")[-1].replace("_", " ").strip().capitalize(), "kind": "tool",
         "status": "failed" if c.is_error else done.get(c.status, "running")}
        for c in calls
    ]


__all__ = ["MAX_NOTES", "NOTE_PREFIX", "outline", "run_steps", "step_notes"]
