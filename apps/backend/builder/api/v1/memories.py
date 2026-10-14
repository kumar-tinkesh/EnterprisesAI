"""An agent's long-term memory of the caller (mounted under ``/api/v1/builder``).

    GET    /agents/{agent_id}/memories               what it remembers about me, newest first
    POST   /agents/{agent_id}/memories               tell it something to remember: {"content": "..."}
    DELETE /agents/{agent_id}/memories/{memory_id}   forget one
    DELETE /agents/{agent_id}/memories               forget everything about me

Only ever the caller's own memories (see ``builder.agents.memory``); the
agent's owner can't read what it remembers about a teammate.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.agents.config import AgentConfig
from builder.agents.memory import load_memories, save_memory
from builder.api.v1.agents import get_agent
from builder.api.v1.deps import get_end_user
from builder.models import BuilderAgentMemory
from builder.runs.db import as_utc

router = APIRouter()


class MemoryOut(BaseModel):
    id: str
    content: str
    # Saved by the agent in a run (its id), or added by the person (None).
    source_run_id: str | None
    created_at: datetime


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)


def _out(m: BuilderAgentMemory) -> MemoryOut:
    return MemoryOut(id=m.id, content=m.content, source_run_id=m.source_run_id, created_at=as_utc(m.created_at))


@router.get("/agents/{agent_id}/memories", response_model=list[MemoryOut])
async def list_memories(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    return [_out(m) for m in await load_memories(db, agent_id=agent.id, owner_id=user.id, limit=500)]


@router.post("/agents/{agent_id}/memories", response_model=MemoryOut, status_code=201)
async def add_memory(
    agent_id: str, payload: MemoryIn, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    config = AgentConfig.model_validate(agent.config or {})
    memory = await save_memory(
        db, tenant_id=user.tenant_id, agent_id=agent.id, owner_id=user.id, content=payload.content,
        max_items=config.memory.max_items,
    )
    if memory is None:
        raise HTTPException(status_code=409, detail="It already remembers that.")
    await db.commit()
    await db.refresh(memory)
    return _out(memory)


@router.delete("/agents/{agent_id}/memories/{memory_id}", status_code=204)
async def forget(agent_id: str, memory_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    memory = (
        await db.execute(
            select(BuilderAgentMemory).where(
                BuilderAgentMemory.id == memory_id, BuilderAgentMemory.agent_id == agent_id, BuilderAgentMemory.owner_id == user.id,
            )
        )
    ).scalars().first()
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(memory)
    await db.commit()


@router.delete("/agents/{agent_id}/memories", status_code=204)
async def forget_all(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    await db.execute(delete(BuilderAgentMemory).where(BuilderAgentMemory.agent_id == agent.id, BuilderAgentMemory.owner_id == user.id))
    await db.commit()
