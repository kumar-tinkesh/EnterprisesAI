"""Agent endpoints (mounted at ``/api/v1/builder/agents``).

    GET    ""                       list (standalone by default; ?workflow_id= for a workflow's own)
    POST   ""                       create (optionally as a workflow's own agent)
    GET    /{agent_id}              one
    PATCH  /{agent_id}              update (optimistic: expected_version)
    DELETE /{agent_id}              delete — refused while a workflow step still uses it
    GET    /{agent_id}/preflight    can the caller run it right now?
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.agents.config import AgentConfig
from builder.api.v1.definitions import AgentCreate, AgentOut, AgentUpdate, CheckResult, Problem
from builder.api.v1.deps import can_manage, get_end_user, problems_response, version_conflict
from builder.models import BuilderAgent, BuilderWorkflow
from builder.services.references import agent_config_problems

router = APIRouter()


def agent_out(agent: BuilderAgent, user: CurrentUser) -> AgentOut:
    return AgentOut(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        goal=agent.goal,
        instructions=agent.instructions or "",
        llm_provider=agent.llm_provider or "",
        llm_model=agent.llm_model or "",
        config=agent.config or {},
        workflow_id=agent.workflow_id,
        owner_id=agent.owner_id,
        version=agent.version,
        can_manage=can_manage(agent.owner_id, user),
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def get_agent(db: AsyncSession, agent_id: str, user: CurrentUser) -> BuilderAgent:
    agent = (
        await db.execute(
            select(BuilderAgent).where(BuilderAgent.id == agent_id, BuilderAgent.tenant_id == user.tenant_id)
        )
    ).scalars().first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def workflows_using(db: AsyncSession, tenant_id: str, agent_id: str) -> list[BuilderWorkflow]:
    workflows = (await db.execute(select(BuilderWorkflow).where(BuilderWorkflow.tenant_id == tenant_id))).scalars()
    return [
        wf for wf in workflows
        if any(n.get("type") == "agent" and n.get("agent_id") == agent_id for n in wf.nodes or [])
    ]


@router.get("", response_model=list[AgentOut])
async def list_agents(
    workflow_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BuilderAgent).where(BuilderAgent.tenant_id == user.tenant_id)
    query = query.where(BuilderAgent.workflow_id == workflow_id if workflow_id else BuilderAgent.workflow_id.is_(None))
    agents = (await db.execute(query.order_by(BuilderAgent.updated_at.desc()))).scalars().all()
    return [agent_out(a, user) for a in agents]


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    payload: AgentCreate,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.workflow_id:
        workflow = (
            await db.execute(
                select(BuilderWorkflow).where(
                    BuilderWorkflow.id == payload.workflow_id, BuilderWorkflow.tenant_id == user.tenant_id
                )
            )
        ).scalars().first()
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if not can_manage(workflow.owner_id, user):
            raise HTTPException(status_code=403, detail="Only the workflow's creator or a tenant admin can add agents to it.")

    problems = await agent_config_problems(db, user, payload.config, check_connection=False)
    if problems:
        return problems_response("This agent points at things that can't be used.", problems)

    agent = BuilderAgent(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        workflow_id=payload.workflow_id,
        name=payload.name.strip(),
        role=payload.role.strip(),
        goal=payload.goal.strip(),
        instructions=payload.instructions.strip(),
        llm_provider=payload.llm_provider.strip(),
        llm_model=payload.llm_model.strip(),
        config=payload.config.model_dump(),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent_out(agent, user)


@router.get("/{agent_id}", response_model=AgentOut)
async def read_agent(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return agent_out(await get_agent(db, agent_id, user), user)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    if not can_manage(agent.owner_id, user):
        raise HTTPException(status_code=403, detail="Only the agent's creator or a tenant admin can change it.")
    if payload.expected_version is not None and payload.expected_version != agent.version:
        raise version_conflict(agent.version)

    if payload.config is not None:
        problems = await agent_config_problems(db, user, payload.config, check_connection=False)
        if problems:
            return problems_response("This agent points at things that can't be used.", problems)
        agent.config = payload.config.model_dump()
    for field in ("name", "role", "goal", "instructions", "llm_provider", "llm_model"):
        value = getattr(payload, field)
        if value is not None:
            setattr(agent, field, value.strip())
    agent.version += 1
    await db.commit()
    await db.refresh(agent)
    return agent_out(agent, user)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    if not can_manage(agent.owner_id, user):
        raise HTTPException(status_code=403, detail="Only the agent's creator or a tenant admin can delete it.")
    users = await workflows_using(db, user.tenant_id, agent.id)
    if users:
        names = ", ".join(f'"{wf.name}"' for wf in users[:5])
        raise HTTPException(status_code=409, detail=f"This agent is used by workflow {names}. Remove those steps first.")
    await db.delete(agent)
    await db.commit()


@router.get("/{agent_id}/preflight", response_model=CheckResult)
async def preflight_agent(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    config = AgentConfig.model_validate(agent.config or {})
    problems = await agent_config_problems(db, user, config, check_connection=True)
    return CheckResult(ok=not problems, problems=[Problem(**p.as_dict()) for p in problems])
