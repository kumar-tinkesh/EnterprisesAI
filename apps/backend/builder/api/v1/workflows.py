"""Workflow endpoints (mounted at ``/api/v1/builder/workflows``).

    GET    ""                          list
    POST   ""                          create
    POST   /validate                   check a graph without saving (canvas live checks)
    GET    /{workflow_id}              one, with its own agents
    PATCH  /{workflow_id}              update (optimistic: expected_version)
    DELETE /{workflow_id}              delete it and its own agents
    POST   /{workflow_id}/preflight    can the caller run it right now?

Saving refuses a graph with any structural or reference problem (422 with
every problem listed). Preflight adds the per-user check — is each server
connected for the person about to run it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.agents.config import AgentConfig
from builder.api.v1.agents import agent_out
from builder.api.v1.definitions import (
    CheckResult,
    Problem,
    WorkflowCreate,
    WorkflowOut,
    WorkflowSummary,
    WorkflowUpdate,
    WorkflowValidateRequest,
)
from builder.api.v1.deps import can_manage, get_end_user, problems_response, version_conflict
from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode
from builder.graph.validation import GraphProblem, validate_graph
from builder.models import BuilderAgent, BuilderWorkflow
from builder.services.references import workflow_reference_problems

router = APIRouter()


def _dump(items: list) -> list[dict]:
    return [i.model_dump(exclude_none=True) for i in items]


def _summary(wf: BuilderWorkflow, user: CurrentUser) -> dict:
    return dict(
        id=wf.id,
        name=wf.name,
        description=wf.description or "",
        owner_id=wf.owner_id,
        version=wf.version,
        node_count=len(wf.nodes or []),
        can_manage=can_manage(wf.owner_id, user),
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


async def _workflow_out(db: AsyncSession, wf: BuilderWorkflow, user: CurrentUser) -> WorkflowOut:
    own_agents = (
        await db.execute(select(BuilderAgent).where(BuilderAgent.workflow_id == wf.id).order_by(BuilderAgent.created_at))
    ).scalars().all()
    return WorkflowOut(
        **_summary(wf, user),
        nodes=wf.nodes or [],
        edges=wf.edges or [],
        config=wf.config or {},
        agents=[agent_out(a, user) for a in own_agents],
    )


async def _get_workflow(db: AsyncSession, workflow_id: str, user: CurrentUser) -> BuilderWorkflow:
    wf = (
        await db.execute(
            select(BuilderWorkflow).where(BuilderWorkflow.id == workflow_id, BuilderWorkflow.tenant_id == user.tenant_id)
        )
    ).scalars().first()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


async def mint_draft_agents(db: AsyncSession, wf: BuilderWorkflow, nodes: list[WorkflowNode], user: CurrentUser) -> list[WorkflowNode]:
    """Turn each agent step's ``draft_agent`` into one of this workflow's own
    agents (a draft on a step that already had an agent replaces it for this
    workflow only — a shared agent is never changed from here)."""
    out: list[WorkflowNode] = []
    for node in nodes:
        draft = node.draft_agent if node.type == "agent" else None
        if draft is None:
            out.append(node)
            continue
        agent = BuilderAgent(
            tenant_id=user.tenant_id,
            owner_id=user.id,
            workflow_id=wf.id,
            name=draft.name.strip(),
            role=draft.role.strip(),
            goal=draft.goal.strip(),
            instructions=draft.instructions.strip(),
            llm_provider=draft.llm_provider.strip(),
            llm_model=draft.llm_model.strip(),
            config=AgentConfig.model_validate(draft.config).model_dump(),
        )
        db.add(agent)
        await db.flush()
        out.append(node.model_copy(update={"agent_id": agent.id, "draft_agent": None}))
    return out


async def check_workflow(
    db: AsyncSession,
    user: CurrentUser,
    *,
    workflow_id: str | None,
    nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
    config: WorkflowConfig,
    check_connection: bool,
) -> list[GraphProblem]:
    problems = validate_graph(nodes, edges)
    problems += await workflow_reference_problems(
        db, user, workflow_id=workflow_id, nodes=nodes, config=config, check_connection=check_connection
    )
    return problems


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    workflows = (
        await db.execute(
            select(BuilderWorkflow)
            .where(BuilderWorkflow.tenant_id == user.tenant_id)
            .order_by(BuilderWorkflow.updated_at.desc())
        )
    ).scalars().all()
    return [WorkflowSummary(**_summary(wf, user)) for wf in workflows]


@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    problems = await check_workflow(
        db, user, workflow_id=None, nodes=payload.nodes, edges=payload.edges, config=payload.config, check_connection=False
    )
    if problems:
        return problems_response("This workflow can't be saved yet.", problems)
    wf = BuilderWorkflow(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        nodes=[],
        edges=_dump(payload.edges),
        config=payload.config.model_dump(),
    )
    db.add(wf)
    await db.flush()
    wf.nodes = _dump(await mint_draft_agents(db, wf, payload.nodes, user))
    await db.commit()
    await db.refresh(wf)
    return await _workflow_out(db, wf, user)


@router.post("/validate", response_model=CheckResult)
async def validate_workflow(
    payload: WorkflowValidateRequest,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.workflow_id:
        await _get_workflow(db, payload.workflow_id, user)
    problems = await check_workflow(
        db,
        user,
        workflow_id=payload.workflow_id,
        nodes=payload.nodes,
        edges=payload.edges,
        config=payload.config,
        check_connection=False,
    )
    return CheckResult(ok=not problems, problems=[Problem(**p.as_dict()) for p in problems])


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def read_workflow(workflow_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return await _workflow_out(db, await _get_workflow(db, workflow_id, user), user)


@router.patch("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    wf = await _get_workflow(db, workflow_id, user)
    if not can_manage(wf.owner_id, user):
        raise HTTPException(status_code=403, detail="Only the workflow's creator or a tenant admin can change it.")
    if payload.expected_version is not None and payload.expected_version != wf.version:
        raise version_conflict(wf.version)

    graph_changed = any(v is not None for v in (payload.nodes, payload.edges, payload.config))
    if graph_changed:
        nodes = payload.nodes if payload.nodes is not None else [WorkflowNode.model_validate(n) for n in wf.nodes or []]
        edges = payload.edges if payload.edges is not None else [WorkflowEdge.model_validate(e) for e in wf.edges or []]
        config = payload.config if payload.config is not None else WorkflowConfig.model_validate(wf.config or {})
        problems = await check_workflow(
            db, user, workflow_id=wf.id, nodes=nodes, edges=edges, config=config, check_connection=False
        )
        if problems:
            return problems_response("This workflow can't be saved yet.", problems)
        nodes = await mint_draft_agents(db, wf, nodes, user)
        wf.nodes, wf.edges, wf.config = _dump(nodes), _dump(edges), config.model_dump()
        # This workflow's own agents that no step uses any more go (e.g. one an
        # edit replaced). Standalone agents are never touched.
        in_use = {n.agent_id for n in nodes if n.type == "agent" and n.agent_id}
        await db.execute(
            delete(BuilderAgent).where(BuilderAgent.workflow_id == wf.id, BuilderAgent.id.not_in(in_use or {""}))
        )
    if payload.name is not None:
        wf.name = payload.name.strip()
    if payload.description is not None:
        wf.description = payload.description.strip()
    wf.version += 1
    await db.commit()
    await db.refresh(wf)
    return await _workflow_out(db, wf, user)


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    wf = await _get_workflow(db, workflow_id, user)
    if not can_manage(wf.owner_id, user):
        raise HTTPException(status_code=403, detail="Only the workflow's creator or a tenant admin can delete it.")
    # Run history stays (runs keep their own snapshot); the workflow's own agents go with it.
    await db.execute(delete(BuilderAgent).where(BuilderAgent.workflow_id == wf.id))
    await db.delete(wf)
    await db.commit()


@router.post("/{workflow_id}/preflight", response_model=CheckResult)
async def preflight_workflow(workflow_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    wf = await _get_workflow(db, workflow_id, user)
    problems = await check_workflow(
        db,
        user,
        workflow_id=wf.id,
        nodes=[WorkflowNode.model_validate(n) for n in wf.nodes or []],
        edges=[WorkflowEdge.model_validate(e) for e in wf.edges or []],
        config=WorkflowConfig.model_validate(wf.config or {}),
        check_connection=True,
    )
    return CheckResult(ok=not problems, problems=[Problem(**p.as_dict()) for p in problems])
