"""Playground chats: a conversation is an ordered list of runs of one agent or
workflow, private to the person who started it (like the runs themselves).

An agent run that is part of a chat gets the chat's recent turns — what was
asked, what the agent answered — as context, so a follow-up ("and the second
one?") makes sense to it. Only finished, answered turns count; at most
``HISTORY_TURNS`` of them, each capped at ``HISTORY_CHARS``.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.models import BuilderApproval, BuilderConversation, BuilderNodeRun, BuilderRun, BuilderToolCall
from builder.runs import states
from builder.runs.db import as_utc, utcnow

HISTORY_TURNS = 8
HISTORY_CHARS = 4000
TITLE_CHARS = 80


class ConversationError(Exception):
    """Raised for a chat that can't be used as asked; ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def chat_order(runs: list[BuilderRun]) -> list[BuilderRun]:
    """Oldest first. ``created_at`` can tie (second resolution on SQLite), but a
    chat's turns run one at a time, so when each started breaks the tie."""
    latest = utcnow()
    return sorted(runs, key=lambda r: (as_utc(r.created_at) or latest, as_utc(r.started_at) or latest))


def title_from(text: str) -> str:
    """The chat's name: its first message, on one line."""
    line = " ".join((text or "").split())
    return _cap(line, TITLE_CHARS) or "New chat"


async def get_conversation(db: AsyncSession, conversation_id: str, user: CurrentUser) -> BuilderConversation:
    conv = (
        await db.execute(
            select(BuilderConversation).where(BuilderConversation.id == conversation_id, BuilderConversation.owner_id == user.id)
        )
    ).scalars().first()
    if conv is None:
        raise ConversationError("Chat not found.")
    return conv


async def open_conversation(
    db: AsyncSession, user: CurrentUser, *, kind: str, target_id: str, conversation_id: str | None, new: bool, text: str
) -> BuilderConversation | None:
    """The chat a new run belongs to: the one named (it must be this user's,
    with this agent/workflow), a new one when ``new``, or none (a one-off run)."""
    if conversation_id:
        conv = await get_conversation(db, conversation_id, user)
        if conv.kind != kind or (conv.agent_id if kind == "agent" else conv.workflow_id) != target_id:
            raise ConversationError("That chat belongs to a different agent or workflow.", status=409)
        busy = (
            await db.execute(
                select(func.count()).select_from(BuilderRun).where(
                    BuilderRun.conversation_id == conv.id, BuilderRun.status.in_(states.ACTIVE)
                )
            )
        ).scalar_one()
        if busy:
            raise ConversationError("Wait for the current answer (or stop it) before sending another message.", status=409)
        return conv
    if not new:
        return None
    conv = BuilderConversation(
        tenant_id=user.tenant_id, owner_id=user.id, kind=kind, title=title_from(text), turn_count=0,
        **({"agent_id": target_id} if kind == "agent" else {"workflow_id": target_id}),
    )
    db.add(conv)
    await db.flush()
    return conv


async def conversation_history(db: AsyncSession, conversation_id: str) -> list[dict]:
    """The chat's recent answered turns as model messages, oldest first."""
    runs = (
        await db.execute(
            select(BuilderRun)
            .where(BuilderRun.conversation_id == conversation_id, BuilderRun.status == states.SUCCEEDED)
            .order_by(BuilderRun.created_at.desc())
            .limit(HISTORY_TURNS)
        )
    ).scalars().all()
    history: list[dict] = []
    for run in chat_order(list(runs)):
        asked, answered = ((run.input or {}).get("text") or "").strip(), (run.output_text or "").strip()
        files = [a.get("filename") for a in (run.input or {}).get("attachments") or [] if a.get("filename")]
        if asked and files:
            # Their content isn't carried over (it can be long); the agent at least knows they were there.
            asked += f"\n[Attached then: {', '.join(files)}]"
        if asked and answered:
            history += [
                {"role": "user", "content": _cap(asked, HISTORY_CHARS)},
                {"role": "assistant", "content": _cap(answered, HISTORY_CHARS)},
            ]
    return history


def record_turn(conv: BuilderConversation) -> None:
    conv.turn_count = (conv.turn_count or 0) + 1
    conv.last_message_at = utcnow()


async def delete_conversation(db: AsyncSession, conv: BuilderConversation) -> None:
    """The chat and every run in it (their steps, tool calls and approvals).
    Refused while one of its runs is still going."""
    run_ids = (await db.execute(select(BuilderRun.id, BuilderRun.status).where(BuilderRun.conversation_id == conv.id))).all()
    if any(status in states.ACTIVE for _, status in run_ids):
        raise ConversationError("This chat is still answering. Stop it first, then delete it.", status=409)
    ids = [rid for rid, _ in run_ids]
    if ids:
        # SQLite doesn't cascade, so children go first (see builder.models).
        for model in (BuilderApproval, BuilderToolCall, BuilderNodeRun):
            await db.execute(delete(model).where(model.run_id.in_(ids)))
        await db.execute(delete(BuilderRun).where(BuilderRun.id.in_(ids)))
    await db.delete(conv)
    await db.flush()


def conversation_view(conv: BuilderConversation) -> dict:
    return {
        "id": conv.id, "kind": conv.kind, "agent_id": conv.agent_id, "workflow_id": conv.workflow_id,
        "title": conv.title, "turn_count": conv.turn_count or 0,
        "created_at": as_utc(conv.created_at), "last_message_at": as_utc(conv.last_message_at),
    }


__all__ = [
    "ConversationError", "HISTORY_TURNS", "chat_order", "conversation_history", "conversation_view", "delete_conversation",
    "get_conversation", "open_conversation", "record_turn", "title_from",
]
