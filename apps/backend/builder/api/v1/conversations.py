"""Playground chat endpoints (mounted under ``/api/v1/builder``).

    GET    /conversations?agent_id= | ?workflow_id=   my chats, newest first
    GET    /conversations/{id}                        one chat
    GET    /conversations/{id}/runs                   its messages: the runs, oldest first, in full
    PATCH  /conversations/{id}                        rename
    DELETE /conversations/{id}                        delete it and every run in it

A chat starts with its first message: ``POST /agents/{id}/runs`` (or
``/workflows/{id}/runs``) with ``new_conversation: true``, and continues with
``conversation_id``. Chats are private to whoever started them, like runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.deps import get_end_user
from builder.models import BuilderConversation, BuilderRun
from builder.runs.conversations import ConversationError, chat_order, conversation_view, delete_conversation, get_conversation
from builder.runs.service import run_view

router = APIRouter()


class Rename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


async def _get(db: AsyncSession, conversation_id: str, user: CurrentUser) -> BuilderConversation:
    try:
        return await get_conversation(db, conversation_id, user)
    except ConversationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/conversations")
async def list_conversations(
    agent_id: str | None = None,
    workflow_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BuilderConversation).where(BuilderConversation.owner_id == user.id)
    if agent_id:
        query = query.where(BuilderConversation.agent_id == agent_id)
    if workflow_id:
        query = query.where(BuilderConversation.workflow_id == workflow_id)
    rows = (
        await db.execute(
            query.order_by(BuilderConversation.last_message_at.desc(), BuilderConversation.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [conversation_view(c) for c in rows]


@router.get("/conversations/{conversation_id}")
async def read_conversation(conversation_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return conversation_view(await _get(db, conversation_id, user))


@router.get("/conversations/{conversation_id}/runs")
async def conversation_runs(
    conversation_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _get(db, conversation_id, user)
    runs = (
        await db.execute(
            select(BuilderRun)
            .where(BuilderRun.conversation_id == conv.id, BuilderRun.owner_id == user.id)
            .order_by(BuilderRun.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [await run_view(db, r) for r in chat_order(list(runs))]


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str, payload: Rename, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)
):
    conv = await _get(db, conversation_id, user)
    conv.title = " ".join(payload.title.split())[:200] or conv.title
    await db.commit()
    await db.refresh(conv)
    return conversation_view(conv)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_conversation(conversation_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    conv = await _get(db, conversation_id, user)
    try:
        await delete_conversation(db, conv)
    except ConversationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
