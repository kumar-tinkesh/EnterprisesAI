"""Run endpoints (mounted under ``/api/v1/builder``).

    POST /agents/{agent_id}/runs       start an agent run (preflight first) -> 202
    POST /workflows/{workflow_id}/runs start a workflow run (preflight + required inputs) -> 202
    GET  /runs                         my runs (?agent_id= ?workflow_id= ?status=)
    GET  /runs/{run_id}                one run: steps, transcript, tool calls, approvals
    POST /runs/{run_id}/cancel
    GET  /approvals                    my decisions to make (?status=pending)
    POST /approvals/{approval_id}      approve | reject | edit (with arguments)
    WS   /runs/{run_id}/events?token=  live events, after a snapshot

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

from builder.agents.config import AgentConfig
from builder.api.v1.agents import get_agent
from builder.api.v1.deps import get_end_user, problems_response
from builder.models import BuilderApproval, BuilderRun
from builder.runs import states
from builder.runs.db import session_factory
from builder.runs.events import get_event_bus
from builder.runs.service import (
    RunActionError,
    approval_view,
    cancel_run,
    create_agent_run,
    create_workflow_run,
    decide_approval,
    run_view,
)
from builder.services.references import agent_config_problems

router = APIRouter()


class RunStart(BaseModel):
    # May be empty for a workflow started by a manual trigger with only variables.
    input: str = Field(default="", max_length=20_000)
    variables: dict[str, Any] = Field(default_factory=dict)


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
    problems = await agent_config_problems(db, user, AgentConfig.model_validate(agent.config or {}), check_connection=True)
    if problems:
        return problems_response("This agent can't run yet.", problems)
    run = await create_agent_run(db, user, agent, text=payload.input, variables=payload.variables)
    return await run_view(db, run, detail=False)


@router.post("/workflows/{workflow_id}/runs", status_code=202)
async def start_workflow_run(
    workflow_id: str,
    payload: RunStart,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    from builder.api.v1.workflows import _get_workflow, check_workflow
    from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode
    from builder.graph.validation import GraphProblem

    wf = await _get_workflow(db, workflow_id, user)
    nodes = [WorkflowNode.model_validate(n) for n in wf.nodes or []]
    if not nodes:
        raise HTTPException(status_code=422, detail="This workflow has no steps yet.")
    problems = await check_workflow(
        db, user, workflow_id=wf.id, nodes=nodes,
        edges=[WorkflowEdge.model_validate(e) for e in wf.edges or []],
        config=WorkflowConfig.model_validate(wf.config or {}), check_connection=True,
    )
    for node in nodes:
        for var in node.variables or []:
            if var.required and payload.variables.get(var.name) in (None, ""):
                problems.append(GraphProblem("missing_variable", f'Fill in "{var.label or var.name}" to run this workflow.', node.id))
    if problems:
        return problems_response("This workflow can't run yet.", problems)
    run = await create_workflow_run(db, user, wf, text=payload.input, variables=payload.variables)
    return await run_view(db, run, detail=False)


@router.get("/runs")
async def list_runs(
    agent_id: str | None = None,
    workflow_id: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BuilderRun).where(BuilderRun.owner_id == user.id)
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
    return [approval_view(a) for a in approvals]


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
