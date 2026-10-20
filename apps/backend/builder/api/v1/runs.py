"""Run endpoints (mounted under ``/api/v1/builder``).

    POST /agents/{agent_id}/runs       start an agent run (preflight first) -> 202
    POST /workflows/{workflow_id}/runs start a workflow run (preflight + required inputs) -> 202
    GET  /runs                         my runs (?agent_id= ?workflow_id= ?status=)
    GET  /runs/{run_id}                one run: steps, transcript, tool calls, approvals
    POST /runs/{run_id}/cancel
    GET  /approvals                    my decisions to make (?status=pending)
    POST /approvals/{approval_id}      approve | reject | edit (with arguments)
    WS   /runs/{run_id}/events?token=  live events, after a snapshot (an answer being written comes as
                                       "output_delta" {node_id, turn, at, text} unless the run was started with stream: false)

A run is visible only to the person who started it: it holds results from
their own connected accounts (their mail, their files), even when the agent
itself is shared in the tenant.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.security import decode_token
from src.db.session import get_db
from src.models import User

from builder.api.v1.agents import get_agent
from builder.api.v1.attachments import attachments_for_run
from builder.api.v1.deps import get_end_user, problems_response
from builder.models import BuilderApproval, BuilderRun
from builder.runs import states
from builder.runs.db import session_factory
from builder.runs.conversations import ConversationError, conversation_history, open_conversation, record_turn
from builder.runs.events import get_event_bus
from builder.runs.service import (
    RunActionError,
    approval_view,
    callers_of,
    cancel_run,
    create_agent_run,
    create_workflow_run,
    decide_approval,
    run_view,
)
from builder.runs.start import agent_run_problems, workflow_run_problems

router = APIRouter()


class RunStart(BaseModel):
    # May be empty for a workflow started by a manual trigger with only variables.
    input: str = Field(default="", max_length=20_000)
    variables: dict[str, Any] = Field(default_factory=dict)
    # How much answer: "auto" sizes it to the question.
    depth: Literal["auto", "short", "detailed"] = "auto"
    # A playground chat: continue this one, or start a new one with this message.
    conversation_id: str | None = None
    new_conversation: bool = False
    # Files uploaded to /attachments, sent with this message (agents only).
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    # Send the answer as it's written ("output_delta" events on /runs/{id}/events).
    stream: bool = True


class Decision(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    arguments: dict[str, Any] | None = None


async def _get_run(db: AsyncSession, run_id: str, user: CurrentUser) -> BuilderRun:
    run = (
        await db.execute(select(BuilderRun).where(BuilderRun.id == run_id, BuilderRun.owner_id == user.id))
    ).scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def _open_chat(db: AsyncSession, user: CurrentUser, kind: str, target_id: str, payload: RunStart):
    """The chat this run is a message of (after preflight passed, so a run that
    can't start never creates an empty chat)."""
    try:
        conv = await open_conversation(
            db, user, kind=kind, target_id=target_id, conversation_id=payload.conversation_id,
            new=payload.new_conversation, text=payload.input,
        )
    except ConversationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    if conv:
        record_turn(conv)
    return conv


@router.post("/agents/{agent_id}/runs", status_code=202)
async def start_agent_run(
    agent_id: str,
    payload: RunStart,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    if not payload.input.strip():
        raise HTTPException(status_code=422, detail="Tell the agent what to do.")
    attachments = await attachments_for_run(db, user, payload.attachment_ids)
    problems = await agent_run_problems(db, user, agent)
    if problems:
        return problems_response("This agent can't run yet.", problems)
    conv = await _open_chat(db, user, "agent", agent.id, payload)
    history = await conversation_history(db, conv.id) if conv else None
    run = await create_agent_run(
        db, user, agent, text=payload.input, variables=payload.variables, depth=payload.depth,
        conversation_id=conv.id if conv else None, history=history, attachments=attachments, stream=payload.stream,
    )
    return await run_view(db, run, detail=False)


@router.post("/workflows/{workflow_id}/runs", status_code=202)
async def start_workflow_run(
    workflow_id: str,
    payload: RunStart,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    from builder.api.v1.workflows import _get_workflow

    wf = await _get_workflow(db, workflow_id, user)
    if not wf.nodes:
        raise HTTPException(status_code=422, detail="This workflow has no steps yet.")
    problems = await workflow_run_problems(db, user, wf, payload.variables)
    if problems:
        return problems_response("This workflow can't run yet.", problems)
    conv = await _open_chat(db, user, "workflow", wf.id, payload)
    run = await create_workflow_run(
        db, user, wf, text=payload.input, variables=payload.variables, depth=payload.depth,
        conversation_id=conv.id if conv else None, stream=payload.stream,
    )
    return await run_view(db, run, detail=False)


class StepTest(BaseModel):
    """One step of a workflow as it is on the canvas (saved or not) and what to give it."""

    node: dict[str, Any]
    input: str = Field(default="", max_length=20_000)
    variables: dict[str, Any] = Field(default_factory=dict)


# Steps that do something by themselves (a condition or an approval only means something between other steps).
TESTABLE_STEPS = ("agent", "tool")


@router.post("/workflows/{workflow_id}/steps/test", status_code=202)
async def test_workflow_step(
    workflow_id: str,
    payload: StepTest,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    """Run one step by itself: input → the step → output, on the normal queue.

    The step is taken as sent, so unsaved edits (overrides, a new agent still
    being drafted, pinned tool values) are what runs. It's a real run (tools
    really act), kept out of run history and the person's memory
    (``purpose="step"``)."""
    from builder.api.v1.workflows import _get_workflow
    from builder.agents.config import AgentConfig
    from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode
    from builder.runs.service import create_run, workflow_definition
    from builder.services.references import check_workflow

    wf = await _get_workflow(db, workflow_id, user)
    try:
        node = WorkflowNode.model_validate(payload.node)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"This step isn't valid: {exc}") from exc
    if node.type not in TESTABLE_STEPS:
        raise HTTPException(status_code=422, detail="Only agent and tool steps can be tested on their own.")
    node = node.model_copy(update={"id": "step", "retry": None})
    nodes = [WorkflowNode(id="in", type="input"), node, WorkflowNode(id="out", type="output")]
    edges = [WorkflowEdge(id="e1", source="in", target="step"), WorkflowEdge(id="e2", source="step", target="out")]
    config = WorkflowConfig.model_validate(wf.config or {})
    problems = await check_workflow(db, user, workflow_id=wf.id, nodes=nodes, edges=edges, config=config, check_connection=True)
    if problems:
        return problems_response("This step can't run yet.", problems)

    snapshot = {
        "id": wf.id, "name": f"{wf.name} · {node.label or node.type.replace('_', ' ')}",
        "nodes": [n.model_dump(mode="json", exclude_none=True) for n in nodes],
        "edges": [e.model_dump(mode="json", exclude_none=True) for e in edges],
        "config": config.model_dump(mode="json"), "version": wf.version,
    }
    frozen: dict[str, dict] = {}
    if node.type == "agent" and node.draft_agent is not None:
        # A new agent isn't saved until the workflow is: it runs from its draft.
        draft, draft_id = node.draft_agent, f"draft-{wf.id}"
        frozen[draft_id] = {
            "id": draft_id, "name": draft.name, "role": draft.role, "goal": draft.goal,
            "instructions": draft.instructions or "", "llm_provider": draft.llm_provider or "",
            "llm_model": draft.llm_model or "", "config": AgentConfig.model_validate(draft.config).model_dump(), "version": 0,
        }
        snapshot["nodes"][1] = {**snapshot["nodes"][1], "agent_id": draft_id}
        snapshot["nodes"][1].pop("draft_agent", None)
    definition = await workflow_definition(db, user.tenant_id, snapshot, frozen)
    run = await create_run(
        db, user, "workflow", wf.id, definition=definition, version=wf.version,
        text=payload.input, variables=payload.variables, purpose="step",
    )
    return await run_view(db, run, detail=False)


@router.get("/runs")
async def list_runs(
    agent_id: str | None = None,
    workflow_id: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    # Test-case and public (published-key) runs are kept out of run history unless asked for.
    purpose: str = Query(default="run", pattern="^(run|test|public)$"),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BuilderRun).where(BuilderRun.owner_id == user.id, BuilderRun.purpose == purpose)
    if agent_id:
        query = query.where(BuilderRun.agent_id == agent_id)
    if workflow_id:
        query = query.where(BuilderRun.workflow_id == workflow_id)
    if status_:
        query = query.where(BuilderRun.status == status_)
    runs = (await db.execute(query.order_by(BuilderRun.created_at.desc()).limit(limit))).scalars().all()
    return [await run_view(db, r, detail=False) for r in runs]


@router.get("/runs/{run_id}")
async def read_run(run_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return await run_view(db, await _get_run(db, run_id, user))


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    run = await _get_run(db, run_id, user)
    if not await cancel_run(db, run):
        raise HTTPException(status_code=409, detail=f"This run already {run.status}.")
    return await run_view(db, run, detail=False)


@router.get("/approvals")
async def list_approvals(
    status_: str | None = Query(default=states.APPROVAL_PENDING, alias="status"),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BuilderApproval).where(BuilderApproval.owner_id == user.id)
    if status_:
        query = query.where(BuilderApproval.status == status_)
    approvals = (await db.execute(query.order_by(BuilderApproval.created_at.desc()).limit(200))).scalars().all()
    # Runs started through a share link: whose request each one is.
    run_callers = dict((await db.execute(
        select(BuilderRun.id, BuilderRun.caller_user_id).where(BuilderRun.id.in_({a.run_id for a in approvals}), BuilderRun.caller_user_id.is_not(None))
    )).tuples().all()) if approvals else {}
    people = await callers_of(db, run_callers.values())
    return [approval_view(a, people.get(run_callers.get(a.run_id, ""))) for a in approvals]


@router.post("/approvals/{approval_id}")
async def decide(
    approval_id: str,
    payload: Decision,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    approval = (
        await db.execute(select(BuilderApproval).where(BuilderApproval.id == approval_id, BuilderApproval.owner_id == user.id))
    ).scalars().first()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    try:
        approval = await decide_approval(db, user, approval, decision=payload.decision, arguments=payload.arguments)
    except RunActionError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "errors": exc.errors})
    return approval_view(approval)


# ── Live events ──────────────────────────────────────────────────────────────


async def websocket_user(token: str) -> CurrentUser | None:
    """Browsers can't set headers on a WebSocket, so the access token comes as ?token=."""
    try:
        claims = decode_token(token, expected_type="access")
    except pyjwt.PyJWTError:
        return None
    async with session_factory() as db:
        user = await db.get(User, claims.get("sub"))
    if user is None or not user.is_active or not user.tenant_id:
        return None
    return CurrentUser(id=user.id, email=user.email, full_name=user.full_name, role=user.role, tenant_id=user.tenant_id)


async def _send(websocket, data: dict) -> None:
    await websocket.send_json(jsonable_encoder(data))


async def stream_run_events(websocket, run_id: str, *, idle_seconds: float = 15.0) -> None:
    """Snapshot, then live events, until the run finishes or the client leaves.

    Subscribes *before* taking the snapshot so nothing that happens in
    between is missed (at worst something arrives twice).
    """
    async with get_event_bus().subscribe(run_id) as subscription:
        async with session_factory() as db:
            run = await db.get(BuilderRun, run_id)
            await _send(websocket, {"type": "snapshot", "run": await run_view(db, run)})
        if run.status in states.TERMINAL:
            return
        while True:
            event = await subscription.get(timeout=idle_seconds)
            if event is None:
                async with session_factory() as db:
                    run = await db.get(BuilderRun, run_id)
                    if run.status in states.TERMINAL:
                        await _send(websocket, {"type": "snapshot", "run": await run_view(db, run)})
                        return
                await _send(websocket, {"type": "ping"})
                continue
            await _send(websocket, event)
            if event.get("type") == "run_status" and event.get("status") in states.TERMINAL:
                async with session_factory() as db:
                    run = await db.get(BuilderRun, run_id)
                    await _send(websocket, {"type": "snapshot", "run": await run_view(db, run)})
                return


@router.websocket("/runs/{run_id}/events")
async def run_events(websocket: WebSocket, run_id: str, token: str = Query(...)):
    user = await websocket_user(token)
    if user is None:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    async with session_factory() as db:
        run = await db.get(BuilderRun, run_id)
    if run is None or run.owner_id != user.id:
        await websocket.close(code=4404, reason="Run not found")
        return
    await websocket.accept()
    try:
        await stream_run_events(websocket, run_id)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        return
    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
