"""Starting, cancelling and steering runs — what the API calls.

These write the database first and only then nudge the queue, so a crash
between the two leaves a queued run the reaper will send again, never a
message for a run that doesn't exist.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.models import BuilderAgent, BuilderApproval, BuilderNodeRun, BuilderRun, BuilderToolCall
from builder.runs import states
from builder.runs.db import utcnow
from builder.runs.events import emit
from builder.runs.queue import enqueue_run
from builder.services.tool_runtime import validate_arguments

TRANSCRIPT_CHARS = 4000
RESULT_PREVIEW_CHARS = 1000


class RunActionError(Exception):
    def __init__(self, status_code: int, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.status_code, self.message, self.errors = status_code, message, errors or []


def agent_snapshot(agent: BuilderAgent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "goal": agent.goal,
        "instructions": agent.instructions or "",
        "llm_provider": agent.llm_provider or "",
        "llm_model": agent.llm_model or "",
        "config": agent.config or {},
        "version": agent.version,
    }


async def create_agent_run(
    db: AsyncSession, user: CurrentUser, agent: BuilderAgent, *, text: str, variables: dict | None = None
) -> BuilderRun:
    run = BuilderRun(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        kind="agent",
        agent_id=agent.id,
        definition_version=agent.version,
        definition={"agent": agent_snapshot(agent)},
        input={"text": text, "variables": variables or {}},
        status=states.QUEUED,
        state={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await enqueue_run(run.id)
    await emit(run.id, "run_status", status=states.QUEUED)
    return run


def workflow_snapshot(workflow) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "nodes": workflow.nodes or [],
        "edges": workflow.edges or [],
        "config": workflow.config or {},
        "version": workflow.version,
    }


async def create_workflow_run(
    db: AsyncSession, user: CurrentUser, workflow, *, text: str, variables: dict | None = None
) -> BuilderRun:
    """Freezes the workflow and every agent its steps use, so edits made while
    it runs (or before a resume) don't change what this run does."""
    agent_ids = {n.get("agent_id") for n in workflow.nodes or [] if n.get("type") == "agent" and n.get("agent_id")}
    agents = (
        await db.execute(select(BuilderAgent).where(BuilderAgent.id.in_(agent_ids), BuilderAgent.tenant_id == user.tenant_id))
    ).scalars().all() if agent_ids else []
    run = BuilderRun(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        kind="workflow",
        workflow_id=workflow.id,
        definition_version=workflow.version,
        definition={"workflow": workflow_snapshot(workflow), "agents": {a.id: agent_snapshot(a) for a in agents}},
        input={"text": text, "variables": variables or {}},
        status=states.QUEUED,
        state={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await enqueue_run(run.id)
    await emit(run.id, "run_status", status=states.QUEUED)
    return run


async def cancel_run(db: AsyncSession, run: BuilderRun) -> bool:
    if run.status in states.TERMINAL:
        return False
    # A worker still executing it notices on its next heartbeat (status is no
    # longer "running") and stops; its later writes are lease-guarded.
    run.status, run.finished_at, run.error = states.CANCELLED, utcnow(), "Cancelled by the user."
    run.lease_owner = run.lease_expires_at = None
    await db.execute(
        update(BuilderApproval)
        .where(BuilderApproval.run_id == run.id, BuilderApproval.status == states.APPROVAL_PENDING)
        .values(status=states.APPROVAL_EXPIRED, resolved_at=utcnow())
    )
    await db.commit()
    await emit(run.id, "run_status", status=states.CANCELLED)
    return True


async def decide_approval(
    db: AsyncSession, user: CurrentUser, approval: BuilderApproval, *, decision: str, arguments: dict | None
) -> BuilderApproval:
    if approval.status != states.APPROVAL_PENDING:
        raise RunActionError(409, "This was already decided.")
    run = await db.get(BuilderRun, approval.run_id)
    if run is None or run.status in states.TERMINAL:
        raise RunActionError(409, "This run has already finished.")

    payload = approval.payload or {}
    if decision == "edit":
        if not isinstance(arguments, dict):
            raise RunActionError(422, "Give the edit as an object.")
        if approval.kind == states.KIND_HUMAN_STEP:
            if not isinstance(arguments.get("text"), str) or not arguments["text"].strip():
                raise RunActionError(422, 'An approval step\'s edit is {"text": "..."}: the text the workflow continues with.')
        elif approval.kind in (states.KIND_TOOL_CALL, states.KIND_MISSING_INPUT):
            # Missing details are merged into what the step already had.
            full = {**(payload.get("arguments") or {}), **arguments} if approval.kind == states.KIND_MISSING_INPUT else arguments
            try:
                validate_arguments(payload.get("input_schema"), full)
            except Exception as exc:  # InvalidArguments
                raise RunActionError(422, getattr(exc, "message", str(exc)), getattr(exc, "errors", [])) from exc
        else:
            raise RunActionError(422, "This decision can only be approved or rejected.")
        approval.status, approval.edited_input = states.APPROVAL_EDITED, arguments
    elif decision == "approve":
        if approval.kind == states.KIND_MISSING_INPUT:
            raise RunActionError(422, "Fill in the missing details (decision \"edit\" with the arguments) or reject.")
        approval.status = states.APPROVAL_APPROVED
    elif decision == "reject":
        approval.status = states.APPROVAL_REJECTED
    else:
        raise RunActionError(422, "decision must be approve, reject or edit.")
    approval.resolved_by, approval.resolved_at = user.id, utcnow()

    still_pending = (
        await db.execute(
            select(func.count(BuilderApproval.id)).where(
                BuilderApproval.run_id == run.id,
                BuilderApproval.status == states.APPROVAL_PENDING,
                BuilderApproval.id != approval.id,
            )
        )
    ).scalar_one()
    resume = run.status == states.WAITING and not still_pending
    if resume:
        run.status = states.QUEUED
    await db.commit()
    await emit(run.id, "approval_resolved", approval_id=approval.id, status=approval.status)
    if resume:
        await enqueue_run(run.id)
        await emit(run.id, "run_status", status=states.QUEUED)
    return approval


def _cap(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + "…"


def approval_view(a: BuilderApproval) -> dict:
    payload = dict(a.payload or {})
    payload.pop("input_schema", None)
    return {
        "id": a.id, "run_id": a.run_id, "kind": a.kind, "node_id": a.node_id, "tool_name": a.tool_name, "risk": a.risk,
        "status": a.status, "payload": payload, "edited_input": a.edited_input,
        "created_at": a.created_at, "resolved_at": a.resolved_at,
    }


async def run_view(db: AsyncSession, run: BuilderRun, *, detail: bool = True) -> dict:
    view = {
        "id": run.id, "kind": run.kind, "agent_id": run.agent_id, "workflow_id": run.workflow_id,
        "definition_version": run.definition_version, "status": run.status, "input": run.input,
        "output_text": run.output_text, "output": run.output, "error": run.error,
        "prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens,
        "recoveries": run.attempts, "created_at": run.created_at, "started_at": run.started_at, "finished_at": run.finished_at,
        "name": ((run.definition or {}).get("agent") or (run.definition or {}).get("workflow") or {}).get("name"),
    }
    if not detail:
        return view
    node_runs = (await db.execute(select(BuilderNodeRun).where(BuilderNodeRun.run_id == run.id).order_by(BuilderNodeRun.created_at))).scalars().all()
    calls = (await db.execute(select(BuilderToolCall).where(BuilderToolCall.run_id == run.id).order_by(BuilderToolCall.created_at))).scalars().all()
    approvals = (await db.execute(select(BuilderApproval).where(BuilderApproval.run_id == run.id).order_by(BuilderApproval.created_at))).scalars().all()
    view["nodes"] = [
        {
            "node_id": n.node_id, "node_type": n.node_type, "attempt": n.attempt, "status": n.status,
            "output_text": n.output_text, "error": n.error, "prompt_tokens": n.prompt_tokens,
            "completion_tokens": n.completion_tokens, "started_at": n.started_at, "finished_at": n.finished_at,
            "transcript": [
                {k: (_cap(v, TRANSCRIPT_CHARS) if k == "content" else v) for k, v in m.items()}
                for m in (n.state or {}).get("messages", []) if m.get("role") != "system"
            ],
        }
        for n in node_runs
    ]
    view["tool_calls"] = [
        {
            "id": c.id, "node_id": c.node_id, "tool_name": c.tool_name, "server_id": c.server_id, "risk": c.risk,
            "status": c.status, "arguments": c.arguments, "result_preview": _cap(c.result_text, RESULT_PREVIEW_CHARS),
            "is_error": c.is_error, "error": c.error, "duration_ms": c.duration_ms, "created_at": c.created_at,
        }
        for c in calls
    ]
    view["approvals"] = [approval_view(a) for a in approvals]
    return view


__all__ = [
    "RunActionError", "agent_snapshot", "workflow_snapshot", "create_agent_run", "create_workflow_run", "cancel_run", "decide_approval", "run_view", "approval_view",
]
