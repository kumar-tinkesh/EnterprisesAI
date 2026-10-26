"""An agent's webhooks (mounted under ``/api/v1/builder``).

    GET    /agents/{agent_id}/webhooks     mine for this agent
    POST   /agents/{agent_id}/webhooks     make one -> its URL, shown once
    PATCH  /webhooks/{webhook_id}          name, instruction, on/off, requests per minute
    DELETE /webhooks/{webhook_id}

A webhook runs as the person who made it (with their connected tools), so
like a schedule only they see, change or delete it. See
``builder.triggers.webhooks`` for what a post to it does.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.agents import get_agent
from builder.api.v1.deps import get_end_user
from builder.models import BuilderWebhook
from builder.runs.db import as_utc
from builder.triggers.webhooks import new_token

router = APIRouter()


class WebhookOut(BaseModel):
    id: str
    agent_id: str
    name: str
    token_prefix: str
    instruction: str
    enabled: bool
    requests_per_minute: int
    last_used_at: datetime | None
    last_run_id: str | None
    created_at: datetime


class WebhookCreated(WebhookOut):
    # The full URL with its secret token: shown this once.
    url: str


class WebhookIn(BaseModel):
    name: str = Field(default="Webhook", min_length=1, max_length=120)
    instruction: str = Field(default="", max_length=2000)
    requests_per_minute: int = Field(default=10, ge=1, le=60)


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instruction: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    requests_per_minute: int | None = Field(default=None, ge=1, le=60)


def _out(h: BuilderWebhook) -> dict:
    return dict(
        id=h.id, agent_id=h.agent_id, name=h.name, token_prefix=h.token_prefix, instruction=h.instruction or "",
        enabled=h.enabled, requests_per_minute=h.requests_per_minute, last_used_at=as_utc(h.last_used_at),
        last_run_id=h.last_run_id, created_at=as_utc(h.created_at),
    )


def hook_url(request: Request, token: str) -> str:
    """The public URL, on the host this request came in on ("/api/v1/builder/…" -> "/api/v1/public/hooks/…")."""
    base = str(request.base_url).rstrip("/")
    prefix = request.url.path.split("/builder/")[0]
    return f"{base}{prefix}/public/hooks/{token}"


async def _mine(db: AsyncSession, webhook_id: str, user: CurrentUser) -> BuilderWebhook:
    hook = (
        await db.execute(select(BuilderWebhook).where(BuilderWebhook.id == webhook_id, BuilderWebhook.owner_id == user.id))
    ).scalars().first()
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return hook


@router.get("/agents/{agent_id}/webhooks", response_model=list[WebhookOut])
async def list_webhooks(agent_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, agent_id, user)
    rows = (
        await db.execute(
            select(BuilderWebhook)
            .where(BuilderWebhook.agent_id == agent.id, BuilderWebhook.owner_id == user.id)
            .order_by(BuilderWebhook.created_at)
        )
    ).scalars()
    return [WebhookOut(**_out(h)) for h in rows]


@router.post("/agents/{agent_id}/webhooks", response_model=WebhookCreated, status_code=201)
async def create_webhook(
    agent_id: str, payload: WebhookIn, request: Request,
    user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    if agent.workflow_id is not None:
        raise HTTPException(status_code=422, detail="This agent belongs to a workflow; give the workflow a trigger instead.")
    token, token_hash, prefix = new_token()
    hook = BuilderWebhook(
        tenant_id=user.tenant_id, owner_id=user.id, agent_id=agent.id, name=payload.name.strip(),
        token_hash=token_hash, token_prefix=prefix, instruction=payload.instruction.strip(),
        requests_per_minute=payload.requests_per_minute, enabled=True,
    )
    db.add(hook)
    await db.commit()
    await db.refresh(hook)
    return WebhookCreated(**_out(hook), url=hook_url(request, token))


@router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: str, payload: WebhookUpdate, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db),
):
    hook = await _mine(db, webhook_id, user)
    for field in ("name", "instruction"):
        value = getattr(payload, field)
        if value is not None:
            setattr(hook, field, value.strip())
    if payload.enabled is not None:
        hook.enabled = payload.enabled
    if payload.requests_per_minute is not None:
        hook.requests_per_minute = payload.requests_per_minute
    await db.commit()
    await db.refresh(hook)
    return WebhookOut(**_out(hook))


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    hook = await _mine(db, webhook_id, user)
    await db.delete(hook)
    await db.commit()
