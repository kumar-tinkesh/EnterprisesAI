"""Execute a workflow run: schedule steps, run them in parallel, save after each.

    await execute_workflow(run, user, worker_id)   # called by runs.executor with the lease held

Each pass: start every ready step (up to ``PARALLEL_STEPS`` at once), wait
for the first to finish, apply its outcome to the schedule, save. A step is
marked running — and saved — *before* it starts, with its attempt number, so
a run resumed after a crash restarts exactly the steps that were in flight,
under the same attempt: their checkpoints and tool-call records carry over.

Failure policy (workflow config, per-step ``retry`` override):
  retry    try the step again, up to its attempts
  tolerate every line out of it feeds a join that can do without it
  skip     ``on_node_failure: skip`` — pass its input on as if it ran
           (never for a person's "no": a rejected approval always stops)
  abort    otherwise: the run fails, steps still running are stopped

A step waiting on a person doesn't hold up the others: everything that can
still run does, and only then does the run go to ``waiting``.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select, update

from src.api.deps import CurrentUser

from builder.graph.schema import TRIGGER_TYPES, WorkflowConfig
from builder.models import BuilderNodeRun, BuilderRun
from builder.runs import lease, states
from builder.runs.db import session_factory, utcnow
from builder.runs.events import emit
from builder.runs.tool_calls import Paused
from builder.workflows import scheduler as S
from builder.workflows.nodes import RUNNERS, NodeOutcome, StepContext, run_trigger

logger = logging.getLogger("builder.workflows.engine")

PARALLEL_STEPS = 8


class LostLease(Exception):
    pass


async def _save(run_id: str, worker_id: str, state: dict) -> None:
    async with session_factory() as db:
        result = await db.execute(
            update(BuilderRun)
            .where(BuilderRun.id == run_id, BuilderRun.lease_owner == worker_id, BuilderRun.status == states.RUNNING)
            .values(state=state)
        )
        await db.commit()
    if result.rowcount != 1:
        raise LostLease()


async def _node_run(run_id: str, node: dict, attempt: int, input_text: str) -> str:
    async with session_factory() as db:
        row = (
            await db.execute(
                select(BuilderNodeRun).where(
                    BuilderNodeRun.run_id == run_id, BuilderNodeRun.node_id == node["id"], BuilderNodeRun.attempt == attempt
                )
            )
        ).scalars().first()
        if row is None:
            row = BuilderNodeRun(
                run_id=run_id, node_id=node["id"], node_type=node["type"], attempt=attempt,
                status=states.RUNNING, input_text=input_text, started_at=utcnow(), state={},
            )
            db.add(row)
        else:
            row.status = states.RUNNING
        await db.commit()
        return row.id


async def _finish_node(node_run_id: str, status: str, outcome: NodeOutcome | None = None, error: str | None = None) -> None:
    async with session_factory() as db:
        row = await db.get(BuilderNodeRun, node_run_id)
        row.status = status
        if outcome is not None:
            row.output_text = outcome.output if outcome.ok else None
            row.error = outcome.error
            # An agent step already checkpointed its running totals here; the
            # outcome carries the same totals, so this sets rather than adds.
            row.prompt_tokens = outcome.prompt_tokens or row.prompt_tokens
            row.completion_tokens = outcome.completion_tokens or row.completion_tokens
        if error:
            row.error = error
        if status != states.WAITING:
            row.finished_at = utcnow()
        await db.commit()


async def execute_workflow(run: BuilderRun, user: CurrentUser, worker_id: str) -> None:
    definition = run.definition["workflow"]
    config = WorkflowConfig.model_validate(definition.get("config") or {})
    graph = S.build_graph(definition["nodes"], definition["edges"])
    agents = run.definition.get("agents") or {}
    variables = (run.input or {}).get("variables") or {}
    original = (run.input or {}).get("text") or ""

    state = dict(run.state or {})
    if not state.get("nodes"):
        state = S.init_state(graph, original)
    S.resume_interrupted(state)
    await _save(run.id, worker_id, state)
    await emit(run.id, "run_status", status=states.RUNNING)

    session_started = time.monotonic()
    active_before = state.get("active_seconds", 0.0)
    tasks: dict[asyncio.Task, tuple[str, str]] = {}

    async def emit_event(type_: str, **data) -> None:
        await emit(run.id, type_, **data)

    async def run_step(node_id: str, node_run_id: str, attempt: int) -> NodeOutcome:
        node = graph.nodes[node_id]
        n = state["nodes"][node_id]
        if node["type"] in TRIGGER_TYPES:
            return await run_trigger(StepContext(
                run_id=run.id, node=node, node_run_id=node_run_id, attempt=attempt, user=user, graph=graph,
                input_text=n["input"], parts=[tuple(p) for p in n["parts"]], original_input=original,
                failed_inputs=[], agents=agents, approvals=config.approvals, emit=emit_event,
            ), variables)
        ctx = StepContext(
            run_id=run.id, node=node, node_run_id=node_run_id, attempt=attempt, user=user, graph=graph,
            input_text=n["input"] or "", parts=[tuple(p) for p in n["parts"]], original_input=original,
            failed_inputs=state["failed_inputs"].get(node_id, []), agents=agents, approvals=config.approvals,
            emit=emit_event,
        )
        return await RUNNERS[node["type"]](ctx)

    def allowed_tries(node: dict) -> int:
        if node.get("retry"):
            return max(1, int(node["retry"].get("max_attempts") or 1))
        return config.node_retry_count + 1 if config.on_node_failure == "retry" else 1

    async def stop_all() -> None:
        for task in tasks:
            task.cancel()
        for task in list(tasks):
            try:
                await task
            except BaseException:  # noqa: BLE001 — cancelled siblings
                pass
        tasks.clear()

    async def fail_run(message: str) -> None:
        await stop_all()
        state["active_seconds"] = active_before + (time.monotonic() - session_started)
        await _save(run.id, worker_id, state)
        if await lease.release(run.id, worker_id, status=states.FAILED, error=message):
            await emit(run.id, "run_status", status=states.FAILED, error=message)

    try:
        while True:
            elapsed = active_before + (time.monotonic() - session_started)
            if elapsed > config.max_run_seconds:
                await fail_run(f"Stopped: the workflow ran longer than its limit of {config.max_run_seconds}s.")
                return

            for node_id in S.ready(state):
                if len(tasks) >= PARALLEL_STEPS:
                    break
                state["steps"] += 1
                if state["steps"] > config.max_steps:
                    await fail_run(f"Stopped after {config.max_steps} steps — a loop may never be exiting.")
                    return
                n = state["nodes"][node_id]
                n["status"] = S.RUNNING
                node = graph.nodes[node_id]
                await _save(run.id, worker_id, state)
                node_run_id = await _node_run(run.id, node, n["attempt"], n["input"] or "")
                await emit(run.id, "node_status", node_id=node_id, status="running", attempt=n["attempt"])
                task = asyncio.create_task(run_step(node_id, node_run_id, n["attempt"]), name=f"step:{node_id}")
                tasks[task] = (node_id, node_run_id)

            if not tasks:
                break
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                node_id, node_run_id = tasks.pop(task)
                node = graph.nodes[node_id]
                n = state["nodes"][node_id]
                try:
                    outcome = task.result()
                except Paused:
                    n["status"] = S.PAUSED
                    await _finish_node(node_run_id, states.WAITING)
                    await emit(run.id, "node_status", node_id=node_id, status="waiting")
                    continue
                except Exception as exc:  # noqa: BLE001 — a bug in one step fails that step, not the worker
                    logger.exception("workflow step crashed run=%s node=%s", run.id, node_id)
                    outcome = NodeOutcome(ok=False, error=f"Unexpected error: {exc}")

                state["prompt_tokens"] += outcome.prompt_tokens
                state["completion_tokens"] += outcome.completion_tokens
                if outcome.ok:
                    await _finish_node(node_run_id, states.SUCCEEDED, outcome)
                    state["sources"] = list(dict.fromkeys(state["sources"] + outcome.sources))
                    if outcome.final:
                        state["final"] = {"text": outcome.output, "node_id": node_id}
                    S.complete(state, graph, node_id, outcome.output, take=outcome.take)
                    await emit(run.id, "node_status", node_id=node_id, status="succeeded", preview=outcome.output[:300])
                    continue

                await _finish_node(node_run_id, states.FAILED, outcome)
                await emit(run.id, "node_status", node_id=node_id, status="failed", error=outcome.error)
                if not outcome.never_skip and n["tries"] < allowed_tries(node):
                    S.retry(state, node_id)
                elif S.tolerant(graph, node_id) and not outcome.never_skip:
                    S.fail_tolerated(state, graph, node_id, outcome.error or "failed")
                elif config.on_node_failure == "skip" and not outcome.never_skip:
                    S.complete(state, graph, node_id, n["input"] or "")
                else:
                    await fail_run(f'Step "{graph.label(node_id)}" failed: {outcome.error}')
                    return
            state["active_seconds"] = active_before + (time.monotonic() - session_started)
            await _save(run.id, worker_id, state)
    except (LostLease, asyncio.CancelledError):
        await stop_all()
        raise asyncio.CancelledError()

    state["active_seconds"] = active_before + (time.monotonic() - session_started)
    await _save(run.id, worker_id, state)
    if S.paused(state):
        if await lease.release(run.id, worker_id, status=states.WAITING):
            await emit(run.id, "run_status", status=states.WAITING)
        from builder.runs.executor import requeue_if_decided

        await requeue_if_decided(run.id)
        return

    final = state.get("final") or {}
    text = final.get("text")
    if text is None:
        text = "\n\n".join(t for _, t in S.sinks_done(state, graph) if t)
    output = {"text": text, "sources": state["sources"], "final_node": final.get("node_id")}
    await emit(run.id, "output", text=text, sources=state["sources"])
    if await lease.release(
        run.id, worker_id, status=states.SUCCEEDED, output_text=text, output=output,
        prompt_tokens=state["prompt_tokens"], completion_tokens=state["completion_tokens"],
    ):
        await emit(run.id, "run_status", status=states.SUCCEEDED)


__all__ = ["execute_workflow", "PARALLEL_STEPS"]
