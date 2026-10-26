"""How ready an agent or workflow is, and why (mounted under ``/api/v1/builder``).

    GET /{agents|workflows}/{id}/health

Everything is derived from what's already stored: its settings, whether the
caller has connected what it uses, its run history and its test runs. A part
with no evidence yet is "not measured" (and left out of the score) rather than
zero: a fresh agent scoring 0/100 would be a claim about the agent, when it's
really about the missing data. Blockers say what's wrong and how to fix it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from vendor.models import MCPTool

from builder.agents.config import AgentConfig
from builder.api.v1.agents import get_agent
from builder.api.v1.deps import get_end_user
from builder.api.v1.workflows import _get_workflow
from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode, parse_tool_id
from builder.models import BuilderAgent, BuilderRun, BuilderTestRun, BuilderWorkflow
from builder.runs import states
from builder.services.references import agent_config_problems, check_workflow
from builder.services.tool_runtime import classify_tool

router = APIRouter()

Kind = Literal["agents", "workflows"]

# What each part can add to the score: weighted by what a failure there costs
# in front of a real user.
WEIGHTS = {"identity": 10, "structure": 15, "abilities": 15, "safety": 25, "reliability": 20, "testing": 25, "observability": 5}
MIN_RUNS = 5  # fewer finished runs than this isn't a track record
READY_SCORE = 70


@dataclass
class Dim:
    key: str
    label: str
    score: float | None  # 0–1, None = not measured
    summary: str
    detail: list[str] = field(default_factory=list)


@dataclass
class Blocker:
    key: str
    severity: Literal["critical", "warning"]
    title: str
    detail: str
    fix: str


class DimOut(BaseModel):
    key: str
    label: str
    weight: int
    score: int | None
    measured: bool
    summary: str
    detail: list[str]


class BlockerOut(BaseModel):
    key: str
    severity: str
    title: str
    detail: str
    fix: str


class HealthOut(BaseModel):
    score: int | None
    status: Literal["production_ready", "testing", "needs_attention", "not_tested"]
    runs_counted: int
    dimensions: list[DimOut]
    blockers: list[BlockerOut]


async def _risks(db: AsyncSession, tool_ids: list[str]) -> dict[str, str]:
    """tool id → read | edit | delete, the way the runtime classifies it."""
    parsed = {tid: parse_tool_id(tid) for tid in dict.fromkeys(tool_ids)}
    servers = {p[0] for p in parsed.values() if p}
    if not servers:
        return {}
    rows = (await db.execute(select(MCPTool.mcp_server_id, MCPTool.name, MCPTool.annotations).where(MCPTool.mcp_server_id.in_(servers)))).all()
    annotations = {(s, n): a for s, n, a in rows}
    return {tid: classify_tool(p[1], annotations.get((p[0], p[1]))).risk for tid, p in parsed.items() if p}


def _abilities(tools: int, kbs: int, problems: list) -> tuple[Dim, list[Blocker]]:
    blockers: list[Blocker] = []
    not_connected = sorted({p.message.removeprefix("Connect your ").removesuffix(" account first.") for p in problems if p.code == "not_connected"})
    gone = [p for p in problems if p.code in ("server_unavailable", "tool_unavailable", "tool_invalid", "knowledge_base_missing")]
    if not tools and not kbs:
        return Dim("abilities", "Abilities", 0.0, "No tools or knowledge: it can only answer from the model",
                   ["Give it a connector's tools or a knowledge base to work from."]), blockers
    if not_connected:
        blockers.append(Blocker("not_connected", "critical", f"{', '.join(not_connected)} {'is' if len(not_connected) == 1 else 'are'} not connected",
                                "Runs that need these tools will fail for you until you connect them.", "Connect them under Connectors."))
    if gone:
        blockers.append(Blocker("missing_references", "warning", f"{len(gone)} thing{'' if len(gone) == 1 else 's'} it uses no longer exist",
                                "; ".join(dict.fromkeys(p.message for p in gone)), "Remove or replace them in its settings."))
    score = 1.0 - (0.5 if not_connected else 0) - (0.3 if gone else 0)
    parts = [f"{tools} tool{'' if tools == 1 else 's'}" if tools else "", f"{kbs} knowledge base{'' if kbs == 1 else 's'}" if kbs else ""]
    detail = [f"Not connected: {', '.join(not_connected)}"] if not_connected else []
    return Dim("abilities", "Abilities", max(0.0, score), " · ".join(p for p in parts if p), detail), blockers


def _safety(configs: list[AgentConfig], risks: dict[str, str], asks_edit: bool, asks_delete: bool) -> tuple[Dim, list[Blocker]]:
    """Guardrails, weighed against what it can actually do."""
    blockers: list[Blocker] = []
    edits = [t for t, r in risks.items() if r == "edit"]
    deletes = [t for t, r in risks.items() if r == "delete"]
    every = lambda pred: bool(configs) and all(pred(c) for c in configs)  # noqa: E731
    checks = [
        (every(lambda c: c.guardrails.injection), "Refuses attempts to override its instructions", 2),
        (every(lambda c: c.guardrails.pii_input), "Hides personal data in what it's sent", 1),
        (every(lambda c: c.guardrails.pii_output), "Hides personal data in its answers", 1),
        (every(lambda c: bool(c.guardrails.custom_rules)), "Has its own rules to follow", 1),
    ]
    if any(c.knowledge_base_ids for c in configs):
        checks.append((every(lambda c: not c.knowledge_base_ids or c.guardrails.groundedness), "Checks answers against its documents", 2))
    if edits or deletes:
        checks.append(((not edits or asks_edit) and (not deletes or asks_delete), "Asks you before changing or deleting data", 3))
    earned = sum(w for ok, _, w in checks if ok)
    total = sum(w for _, _, w in checks)

    if deletes and not asks_delete:
        names = ", ".join(t.split(":")[-1] for t in deletes[:3]) + ("…" if len(deletes) > 3 else "")
        blockers.append(Blocker("delete_without_approval", "critical", f"{len(deletes)} delete tool{'' if len(deletes) == 1 else 's'} run without asking",
                                f"It can call {names}, and nothing asks a person before data is removed.",
                                "Turn on “Ask before tools run” for delete, or remove those tools."))
    if (edits or deletes) and not every(lambda c: c.guardrails.injection):
        blockers.append(Blocker("writes_without_injection_guard", "critical", "It can change data, and instruction-override protection is off",
                                "Text it reads (a web page, an email) could hide instructions that drive a real change.",
                                "Turn on “Refuse requests that try to override its instructions” under Guardrails."))
    return Dim("safety", "Safety", earned / total if total else 1.0,
               "Fully guarded" if earned == total else f"{earned} of {total} safety points",
               [f"Off: {label}" for ok, label, _ in checks if not ok]), blockers


async def _reliability(db: AsyncSession, user: CurrentUser, column, target_id: str) -> tuple[Dim, list[Blocker], int]:
    rows = (await db.execute(
        select(BuilderRun.status, func.count()).where(column == target_id, BuilderRun.owner_id == user.id, BuilderRun.purpose == "run")
        .group_by(BuilderRun.status)
    )).all()
    counts = dict(rows)
    ok, failed = counts.get(states.SUCCEEDED, 0), counts.get(states.FAILED, 0)
    finished = ok + failed
    if finished < MIN_RUNS:
        return Dim("reliability", "Reliability", None, f"Not measured: {finished} finished run{'' if finished == 1 else 's'}, {MIN_RUNS} needed",
                   ["Chat with it a few times, or run its tests, and this fills in."]), [], finished
    rate = ok / finished
    blockers = []
    if rate < 0.7:
        blockers.append(Blocker("high_failure_rate", "critical", f"{round((1 - rate) * 100)}% of runs fail",
                                f"{failed} of its {finished} finished runs ended in an error.", "Open its recent runs and read what the failures have in common."))
    return Dim("reliability", "Reliability", rate, f"{round(rate * 100)}% of {finished} runs succeeded",
               [f"{failed} failed"] if failed else []), blockers, finished


async def _testing(db: AsyncSession, user: CurrentUser, column, target_id: str) -> tuple[Dim, list[Blocker]]:
    latest = (await db.execute(
        select(BuilderTestRun).where(column == target_id, BuilderTestRun.owner_id == user.id, BuilderTestRun.status == "done", BuilderTestRun.score.is_not(None))
        .order_by(BuilderTestRun.created_at.desc()).limit(1)
    )).scalars().first()
    if latest is None:
        return Dim("testing", "Testing", None, "Not measured: never tested",
                   ["Tests try the cases nobody writes by hand: missing facts, tool failures, attempts to override it."]), []
    failed = latest.total - latest.passed
    weakest = min((latest.dimensions or {}).items(), key=lambda kv: kv[1], default=None)
    blockers = []
    if latest.score < 60 and failed:
        blockers.append(Blocker("low_test_score", "critical" if latest.score < 40 else "warning", f"Last test run scored {latest.score}/100",
                                f"{failed} of {latest.total} cases failed.", "Open Simulate, read the failing cases, and adjust its settings."))
    detail = ([f"{failed} of {latest.total} cases failed"] if failed else []) + ([f"Weakest area: {weakest[0]} at {weakest[1]}%"] if weakest else [])
    return Dim("testing", "Testing", latest.score / 100, f"{latest.score}/100 on the last run ({latest.passed}/{latest.total} passed)", detail), blockers


def _observability(runs: int, configs: list[AgentConfig]) -> Dim:
    checks = [
        (runs > 0, "It has been run"),
        (runs >= MIN_RUNS, "Run enough times to see a pattern"),
        (bool(configs) and all(c.reliability.retries or c.reliability.fallback_model for c in configs), "Has a plan when the model provider fails"),
    ]
    passed = sum(ok for ok, _ in checks)
    return Dim("observability", "Observability", passed / len(checks), f"{runs} finished run{'' if runs == 1 else 's'}" if runs else "Never run",
               [f"Missing: {label}" for ok, label in checks if not ok])


def _verdict(dims: list[Dim], blockers: list[Blocker], runs: int) -> HealthOut:
    measured = [d for d in dims if d.score is not None]
    weight = sum(WEIGHTS[d.key] for d in measured)
    score = round(sum(d.score * WEIGHTS[d.key] for d in measured) / weight * 100) if weight else None
    if runs == 0:
        status = "not_tested"
    elif any(b.severity == "critical" for b in blockers):
        status = "needs_attention"
    elif score is not None and score >= READY_SCORE and runs >= MIN_RUNS and any(d.key == "testing" and d.score is not None for d in dims):
        status = "production_ready"  # never on settings alone: passing tests is the evidence
    else:
        status = "testing"
    return HealthOut(
        score=score, status=status, runs_counted=runs,
        dimensions=[DimOut(key=d.key, label=d.label, weight=WEIGHTS[d.key], score=None if d.score is None else round(d.score * 100),
                           measured=d.score is not None, summary=d.summary, detail=d.detail) for d in dims],
        blockers=[BlockerOut(key=b.key, severity=b.severity, title=b.title, detail=b.detail, fix=b.fix) for b in blockers],
    )


@router.get("/{kind}/{target_id}/health", response_model=HealthOut)
async def health(kind: Kind, target_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await get_agent(db, target_id, user) if kind == "agents" else await _get_workflow(db, target_id, user)
    return await compute_health(db, user, target)


async def compute_health(db: AsyncSession, user: CurrentUser, target: BuilderAgent | BuilderWorkflow) -> HealthOut:
    """The health of an agent/workflow the caller may see (already checked)."""
    dims: list[Dim] = []
    blockers: list[Blocker] = []
    target_id = target.id

    if isinstance(target, BuilderAgent):
        agent = target
        cfg = AgentConfig.model_validate(agent.config or {})
        checks = [
            (bool((agent.name or "").strip()), "has a name"),
            (len((agent.role or "").strip()) >= 8, "its role is specific"),
            (len((agent.goal or "").strip()) >= 25, "its goal says what done looks like"),
            (len((agent.instructions or "").strip()) >= 40, "its instructions give it context"),
        ]
        passed = sum(ok for ok, _ in checks)
        dims.append(Dim("identity", "Identity", passed / len(checks), "Fully described" if passed == len(checks) else f"{passed} of {len(checks)} complete",
                        [f"Missing: {label}" for ok, label in checks if not ok]))
        problems = await agent_config_problems(db, user, cfg, check_connection=True)
        d, b = _abilities(len(cfg.tool_ids), len(cfg.knowledge_base_ids), problems)
        dims.append(d); blockers += b
        d, b = _safety([cfg], await _risks(db, cfg.tool_ids), cfg.approvals.edit, cfg.approvals.delete)
        dims.append(d); blockers += b
        column, test_column, configs = BuilderRun.agent_id, BuilderTestRun.agent_id, [cfg]
    else:
        wf = target
        nodes = [WorkflowNode.model_validate(n) for n in wf.nodes or []]
        edges = [WorkflowEdge.model_validate(e) for e in wf.edges or []]
        wcfg = WorkflowConfig.model_validate(wf.config or {})
        problems = await check_workflow(db, user, workflow_id=wf.id, nodes=nodes, edges=edges, config=wcfg, check_connection=True)

        agent_ids = [n.agent_id for n in nodes if n.type == "agent" and n.agent_id]
        agents = {a.id: a for a in (await db.execute(select(BuilderAgent).where(BuilderAgent.id.in_(agent_ids or [""])))).scalars()}
        configs = [AgentConfig.model_validate(agents[i].config or {}) for i in agent_ids if i in agents]
        configs += [AgentConfig.model_validate(n.draft_agent.config or {}) for n in nodes if n.type == "agent" and n.draft_agent]
        tool_ids = [t for c in configs for t in c.tool_ids] + [n.tool_id for n in nodes if n.type == "tool" and n.tool_id]
        kbs = {k for c in configs for k in c.knowledge_base_ids}

        dims.append(Dim("identity", "Identity", (bool(wf.name.strip()) + (len((wf.description or "").strip()) >= 25)) / 2,
                        "Fully described" if (wf.description or "").strip() else "Has a name, no description",
                        [] if (wf.description or "").strip() else ["Missing: a description of what it does"]))
        structural = [p for p in problems if p.code not in ("not_connected", "server_unavailable", "tool_unavailable", "tool_invalid", "knowledge_base_missing")]
        steps = [n for n in nodes if n.type not in ("input", "manual_trigger", "schedule_trigger", "output")]
        if not nodes:
            dims.append(Dim("structure", "Structure", 0.0, "Empty: no steps yet", ["Add a trigger, the steps, and an Output."]))
        else:
            dims.append(Dim("structure", "Structure", 0.0 if structural else 1.0,
                            f"{len(structural)} problem{'' if len(structural) == 1 else 's'} in its steps" if structural else f"{len(steps)} step{'' if len(steps) == 1 else 's'}, all wired up",
                            list(dict.fromkeys(p.message for p in structural))[:5]))
            if structural:
                blockers.append(Blocker("structure", "critical", "It can't run as built", structural[0].message, "Open it in the editor and fix the marked steps."))
        d, b = _abilities(len(set(tool_ids)), len(kbs), problems)
        dims.append(d); blockers += b
        overrides = wcfg.approval_overrides
        asks = lambda risk: getattr(overrides, risk) == "always" or (getattr(overrides, risk) == "default" and all(getattr(c.approvals, risk) for c in configs))  # noqa: E731
        d, b = _safety(configs, await _risks(db, tool_ids), asks("edit"), asks("delete"))
        dims.append(d); blockers += b
        column, test_column = BuilderRun.workflow_id, BuilderTestRun.workflow_id

    d, b, runs = await _reliability(db, user, column, target_id)
    dims.append(d); blockers += b
    d, b = await _testing(db, user, test_column, target_id)
    dims.append(d); blockers += b
    dims.append(_observability(runs, configs))
    return _verdict(dims, blockers, runs)
