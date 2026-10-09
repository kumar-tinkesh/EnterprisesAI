"""What executing a run means, per kind. Called by a worker that holds the lease.

The executor never decides *whether* to run — the lease did. It loads the
run's frozen definition, runs it as the user who started it, and leaves the
run in exactly one of: waiting (paused on a person), succeeded, failed.
If the task is cancelled (lease lost, run cancelled, worker shutting down)
it leaves everything as checkpointed for whoever picks the run up next.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select, update

from src.api.deps import CurrentUser
from src.models import User

from builder.agents.config import AgentConfig
from builder.agents.runtime import AgentContext, AgentFailed, GuardrailBlocked, Paused, run_agent
from builder.config import get_builder_settings
from builder.models import BuilderApproval, BuilderNodeRun, BuilderRun
from builder.runs import lease, states
from builder.runs.db import session_factory, utcnow
from builder.runs.events import emit
from builder.runs.queue import enqueue_run

logger = logging.getLogger("builder.runs.executor")

AGENT_NODE_ID = "agent"


async def _run_user(owner_id: str) -> CurrentUser | None:
    async with session_factory() as db:
        user = await db.get(User, owner_id)
    if user is None or not user.is_active or not user.tenant_id:
        return None
    return CurrentUser(id=user.id, email=user.email, full_name=user.full_name, role=user.role, tenant_id=user.tenant_id)


async def _finish(run_id: str, worker_id: str, status: str, **values) -> None:
    if await lease.release(run_id, worker_id, status=status, **values):
        await emit(run_id, "run_status", status=status, error=values.get("error"))


async def execute(run_id: str, worker_id: str) -> None:
    async with session_factory() as db:
        run = await db.get(BuilderRun, run_id)
    if run is None:
        return
    if run.attempts > get_builder_settings().RUN_MAX_ATTEMPTS:
        await _finish(run_id, worker_id, states.FAILED, error=f"Stopped after {run.attempts - 1} interrupted attempts.")
        return
    user = await _run_user(run.owner_id)
    if user is None:
        await _finish(run_id, worker_id, states.FAILED, error="The user who started this run no longer has access.")
        return
    await emit(run_id, "run_status", status=states.RUNNING)
    if run.kind == "agent":
        await _execute_agent(run, user, worker_id)
    elif run.kind == "workflow":
        from builder.workflows.engine import execute_workflow

        try:
            await execute_workflow(run, user, worker_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a bug must fail the run, not wedge it
            logger.exception("workflow run crashed run=%s", run.id)
            await _finish(run_id, worker_id, states.FAILED, error=f"Unexpected error: {exc}")
    else:
        await _finish(run_id, worker_id, states.FAILED, error=f"Unknown run kind {run.kind!r}.")


async def requeue_if_decided(run_id: str) -> None:
    """A decision can land between "approval created" and "run marked waiting";
    the decider then saw a running run and didn't re-queue it. Do it here."""
    async with session_factory() as db:
        pending = (
            await db.execute(
                select(func.count(BuilderApproval.id)).where(
                    BuilderApproval.run_id == run_id, BuilderApproval.status == states.APPROVAL_PENDING
                )
            )
        ).scalar_one()
        if pending:
            return
        result = await db.execute(
            update(BuilderRun).where(BuilderRun.id == run_id, BuilderRun.status == states.WAITING).values(status=states.QUEUED)
        )
        await db.commit()
    if result.rowcount:
        await enqueue_run(run_id)


async def _node_run(run: BuilderRun, node_id: str, node_type: str, input_text: str) -> BuilderNodeRun:
    async with session_factory() as db:
        node_run = (
            await db.execute(
                select(BuilderNodeRun)
                .where(BuilderNodeRun.run_id == run.id, BuilderNodeRun.node_id == node_id)
                .order_by(BuilderNodeRun.attempt.desc())
            )
        ).scalars().first()
        if node_run is None:
            node_run = BuilderNodeRun(
                run_id=run.id, node_id=node_id, node_type=node_type, attempt=1,
                status=states.RUNNING, input_text=input_text, started_at=utcnow(), state={},
            )
            db.add(node_run)
        else:
            node_run.status = states.RUNNING
        await db.commit()
        await db.refresh(node_run)
        return node_run


async def _set_node(node_run_id: str, **values) -> None:
    async with session_factory() as db:
        node_run = await db.get(BuilderNodeRun, node_run_id)
        for key, value in values.items():
            setattr(node_run, key, value)
        await db.commit()


async def _execute_agent(run: BuilderRun, user: CurrentUser, worker_id: str) -> None:
    agent = run.definition["agent"]
    config = AgentConfig.model_validate(agent.get("config") or {})
    input_text = (run.input or {}).get("text") or ""
    node_run = await _node_run(run, AGENT_NODE_ID, "agent", input_text)

    async def emit_event(type_: str, **data) -> None:
        await emit(run.id, type_, **data)

    ctx = AgentContext(
        run_id=run.id, node_run_id=node_run.id, node_id=AGENT_NODE_ID, attempt=node_run.attempt,
        user=user, agent=agent, config=config, input_text=input_text, approvals=config.approvals, emit=emit_event,
        dry_run=run.purpose == "test", depth=(run.input or {}).get("depth") or "auto",
    )
    try:
        result = await run_agent(ctx)
    except Paused:
        await _set_node(node_run.id, status=states.WAITING)
        await _finish(run.id, worker_id, states.WAITING)
        await requeue_if_decided(run.id)
    except GuardrailBlocked as exc:
        # Keep what the guardrails found on the run, so it shows after a reload too.
        output = {"text": None, "guardrails": exc.flags}
        await _set_node(node_run.id, status=states.FAILED, error=str(exc), output=output, finished_at=utcnow())
        await _finish(run.id, worker_id, states.FAILED, error=str(exc), output=output)
    except AgentFailed as exc:
        await _set_node(node_run.id, status=states.FAILED, error=str(exc), finished_at=utcnow())
        await _finish(run.id, worker_id, states.FAILED, error=str(exc))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a bug must fail the run, not wedge it
        logger.exception("agent run crashed run=%s", run.id)
        await _set_node(node_run.id, status=states.FAILED, error=f"Unexpected error: {exc}", finished_at=utcnow())
        await _finish(run.id, worker_id, states.FAILED, error=f"Unexpected error: {exc}")
    else:
        output = {"text": result.text, "sources": result.sources, "tool_calls": result.tool_calls, "guardrails": result.guardrails}
        await _set_node(node_run.id, status=states.SUCCEEDED, output_text=result.text, output=output, finished_at=utcnow())
        # Before the final status: listeners stop at a terminal run_status.
        await emit(run.id, "output", text=result.text, sources=result.sources)
        await _finish(
            run.id, worker_id, states.SUCCEEDED, output_text=result.text, output=output,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        )


__all__ = ["execute", "AGENT_NODE_ID"]
