"""One tool call inside a run, made safe to resume — shared by agent steps
and workflow tool steps.

    await ledgered_call(site, tool, call_key, arguments) -> CallOutcome   (may raise Paused)

* The call is recorded in ``BuilderToolCall`` under ``call_key`` *before* it
  is sent. ``call_key`` must be deterministic for the call's place in the
  run, so a resumed run finds the record of what it already did.
* Finished before (succeeded / failed / declined) -> the stored outcome is
  returned; nothing is sent again.
* Needs a yes (the site's approval policy for the tool's risk) -> a
  ``tool_call`` approval; approved / edited -> runs, rejected -> declined.
* In a test run (``site.dry_run``) a data-changing call is recorded and
  answered as if it worked, without being sent or asking anyone: testing an
  agent is no reason to change real records. Read calls run for real.
* Left ``started`` by an interruption, or the connection broke mid-call
  (``may_have_run``): a read tool simply runs again; a data-changing one
  becomes an ``uncertain_call`` approval — "this may already have run, run
  it again?" — and only a yes sends it a second time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select

from src.api.deps import CurrentUser

from builder.agents.tools import AgentTool
from builder.graph.schema import ToolApprovalPolicy
from builder.models import BuilderApproval, BuilderToolCall
from builder.runs import states
from builder.runs.db import session_factory, utcnow
from builder.services.tool_runtime import ToolRuntimeError, ToolUnavailable, classify_tool, invoke_tool, validate_arguments


class Paused(Exception):
    """The run is waiting on a person (an approval)."""

    def __init__(self, approval_id: str):
        super().__init__(approval_id)
        self.approval_id = approval_id


@dataclass
class CallSite:
    """Where in a run a call is made, and on whose behalf."""

    run_id: str
    node_run_id: str
    node_id: str
    user: CurrentUser
    approvals: ToolApprovalPolicy
    timeout: float
    # Shown to the approver: "<requester> wants to run <tool> on <server>".
    requester: str
    emit: Callable[..., Awaitable[None]]
    # A test run: don't send data-changing calls, answer them as if they worked.
    dry_run: bool = False


DRY_RUN_RESULT = (
    "[Test run] This action was not actually performed, because this is a test. "
    "Carry on as if it succeeded."
)


@dataclass
class CallOutcome:
    text: str
    is_error: bool = False
    error: str | None = None
    structured: dict | None = None
    declined: bool = False


async def _ask(db, site: CallSite, ledger: BuilderToolCall, tool: AgentTool, kind: str, arguments: dict) -> BuilderApproval:
    approval = BuilderApproval(
        run_id=site.run_id,
        tenant_id=site.user.tenant_id,
        owner_id=site.user.id,
        kind=kind,
        node_id=site.node_id,
        tool_call_id=ledger.id,
        tool_name=tool.tool_name,
        risk=ledger.risk,
        payload={
            "server_id": tool.server_id,
            "server_name": tool.server_name,
            "tool_name": tool.tool_name,
            "description": tool.description,
            "arguments": arguments,
            "input_schema": tool.input_schema,
            "requester": site.requester,
            "message": (
                f"{tool.tool_name} on {tool.server_name} may already have run before the run was interrupted. Run it again?"
                if kind == states.KIND_UNCERTAIN_CALL
                else f"{site.requester} wants to run {tool.tool_name} on {tool.server_name}."
            ),
        },
    )
    db.add(approval)
    await db.flush()
    return approval


async def _pause(db, site: CallSite, approval: BuilderApproval) -> None:
    await db.commit()
    await site.emit(
        "approval_requested", approval_id=approval.id, kind=approval.kind, tool=approval.tool_name,
        risk=approval.risk, node_id=site.node_id,
    )
    raise Paused(approval.id)


async def ledgered_call(site: CallSite, tool: AgentTool, call_key: str, arguments: dict) -> CallOutcome:
    """Raises ``InvalidArguments`` (before recording anything) if ``arguments``
    don't fit the tool, and ``Paused`` when a person has to decide."""
    risk = classify_tool(tool.tool_name, tool.annotations)

    async with session_factory() as db:
        ledger = (
            await db.execute(select(BuilderToolCall).where(BuilderToolCall.run_id == site.run_id, BuilderToolCall.call_key == call_key))
        ).scalars().first()

        if ledger is not None and ledger.status in states.CALL_DONE:
            return CallOutcome(
                text=ledger.result_text or "", is_error=bool(ledger.is_error), error=ledger.error,
                structured=ledger.result, declined=ledger.status == states.CALL_DECLINED,
            )

        if ledger is None:
            validate_arguments(tool.input_schema, arguments)
            if site.dry_run and risk.risk != "read":
                db.add(BuilderToolCall(
                    run_id=site.run_id, node_run_id=site.node_run_id, node_id=site.node_id, call_key=call_key,
                    server_id=tool.server_id, tool_name=tool.tool_name, risk=risk.risk, arguments=arguments,
                    status=states.CALL_SUCCEEDED, result_text=DRY_RUN_RESULT, is_error=False, finished_at=utcnow(),
                ))
                await db.commit()
                await site.emit("tool_call", phase="started", tool=tool.tool_name, server=tool.server_name, risk=risk.risk,
                                arguments=arguments, node_id=site.node_id, simulated=True)
                await site.emit("tool_call", phase="finished", tool=tool.tool_name, is_error=False, node_id=site.node_id, simulated=True)
                return CallOutcome(text=DRY_RUN_RESULT)
            needs_yes = getattr(site.approvals, risk.risk) and not site.dry_run
            ledger = BuilderToolCall(
                run_id=site.run_id, node_run_id=site.node_run_id, node_id=site.node_id, call_key=call_key,
                server_id=tool.server_id, tool_name=tool.tool_name, risk=risk.risk, arguments=arguments,
                status=states.CALL_AWAITING_APPROVAL if needs_yes else states.CALL_STARTED,
            )
            db.add(ledger)
            await db.flush()
            if needs_yes:
                approval = await _ask(db, site, ledger, tool, states.KIND_TOOL_CALL, arguments)
                ledger.approval_id = approval.id
                await _pause(db, site, approval)

        elif ledger.status == states.CALL_AWAITING_APPROVAL:
            approval = await db.get(BuilderApproval, ledger.approval_id)
            if approval.status == states.APPROVAL_PENDING:
                raise Paused(approval.id)
            if approval.status not in states.APPROVAL_YES:
                ledger.status, ledger.finished_at = states.CALL_DECLINED, utcnow()
                ledger.result_text = "The user declined this tool call."
                await db.commit()
                await site.emit("tool_call", phase="declined", tool=tool.tool_name, node_id=site.node_id)
                return CallOutcome(text=ledger.result_text, declined=True)
            if approval.status == states.APPROVAL_EDITED and approval.edited_input is not None:
                ledger.arguments = approval.edited_input
            ledger.status = states.CALL_STARTED

        elif ledger.status in (states.CALL_STARTED, states.CALL_UNKNOWN) and risk.risk != "read":
            # Sent before an interruption: it may have gone through.
            uncertain = (
                await db.execute(
                    select(BuilderApproval).where(
                        BuilderApproval.tool_call_id == ledger.id, BuilderApproval.kind == states.KIND_UNCERTAIN_CALL
                    )
                )
            ).scalars().first()
            if uncertain is None:
                ledger.status = states.CALL_UNKNOWN
                await _pause(db, site, await _ask(db, site, ledger, tool, states.KIND_UNCERTAIN_CALL, ledger.arguments))
            if uncertain.status == states.APPROVAL_PENDING:
                raise Paused(uncertain.id)
            if uncertain.status not in states.APPROVAL_YES:
                ledger.status, ledger.finished_at = states.CALL_DECLINED, utcnow()
                ledger.result_text = "Not run again: the user said the earlier attempt may already have gone through."
                await db.commit()
                return CallOutcome(text=ledger.result_text, declined=True)
            ledger.status = states.CALL_STARTED
        # else: a read tool left "started" by an interruption — safe to run again.

        arguments = ledger.arguments
        await db.commit()
        ledger_id = ledger.id

    await site.emit(
        "tool_call", phase="started", tool=tool.tool_name, server=tool.server_name, risk=risk.risk,
        arguments=arguments, node_id=site.node_id,
    )
    started = time.monotonic()
    status, structured, is_error, error = states.CALL_SUCCEEDED, None, False, None
    try:
        async with session_factory() as db:
            result = await invoke_tool(
                db, user=site.user, server_id=tool.server_id, tool_name=tool.tool_name, arguments=arguments,
                confirm=True, timeout=site.timeout,
            )
        text, structured, is_error = result.output.text, result.output.structured, result.output.is_error
        if is_error:
            status = states.CALL_FAILED
    except ToolUnavailable as exc:
        if exc.may_have_run and risk.risk != "read":
            async with session_factory() as db:
                ledger = await db.get(BuilderToolCall, ledger_id)
                ledger.status, ledger.error = states.CALL_UNKNOWN, exc.message
                await _pause(db, site, await _ask(db, site, ledger, tool, states.KIND_UNCERTAIN_CALL, arguments))
        status, text, error, is_error = states.CALL_FAILED, f"Tool failed: {exc.message}", exc.message, True
    except ToolRuntimeError as exc:
        status, text, error, is_error = states.CALL_FAILED, f"Tool failed: {exc.message}", exc.message, True

    structured = structured if isinstance(structured, dict) else None
    async with session_factory() as db:
        ledger = await db.get(BuilderToolCall, ledger_id)
        ledger.status, ledger.result_text, ledger.result = status, text, structured
        ledger.is_error, ledger.error = is_error, error
        ledger.duration_ms, ledger.finished_at = int((time.monotonic() - started) * 1000), utcnow()
        await db.commit()
    await site.emit("tool_call", phase="finished", tool=tool.tool_name, is_error=is_error, node_id=site.node_id, preview=text[:300])
    return CallOutcome(text=text, is_error=is_error, error=error, structured=structured)


__all__ = ["CallSite", "CallOutcome", "Paused", "ledgered_call"]
