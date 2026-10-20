"""Publishing (mounted at ``/api/v1/builder``): publishable keys for an agent or workflow.

    GET    /{agents|workflows}/{id}/publish-check   what publishing would expose: write tools, problems, advice
    GET    /{agents|workflows}/{id}/public-keys     its keys (with today's use)
    POST   /{agents|workflows}/{id}/public-keys     make one — the key is in the response, once
    PATCH  /public-keys/{key_id}                    pause/resume, move to another version, limits, origins, share link
    DELETE /public-keys/{key_id}                    revoke (it stops working at once; the record stays)
    GET    /published                               everything the caller published: keys + usage over N days

Publishing is for the agent's/workflow's creator or a tenant admin. A key
runs as whoever made it, with their connected tools — so when callers could
make it use tools that change data, the maker has to say yes to that
explicitly (``acknowledge_write_tools``).

A key can also have a share link (``share``): /r/{share_slug} in the web app,
where anyone who signs in runs it (builder.api.v1.shared) — still as the key's
maker, up to ``per_user_daily_limit`` runs a day each.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.agents.config import AgentConfig
from builder.api.v1.agents import get_agent
from builder.api.v1.deps import can_manage, get_end_user
from builder.api.v1.workflows import _get_workflow
from builder.models import BuilderAgent, BuilderPublicKey, BuilderRun, BuilderVersion, BuilderWorkflow
from builder.publishing.service import (
    PublishError, definition_for, definition_problems, new_key, new_share_slug, start_of_day, usage, write_tools,
)
from builder.runs import states
from builder.runs.db import as_utc, utcnow

router = APIRouter()

Kind = Literal["agents", "workflows"]


def _clean_origins(value: list[str]) -> list[str]:
    out = []
    for o in value:
        o = o.strip().rstrip("/")
        if not o:
            continue
        if not o.startswith(("https://", "http://")) or "/" in o.split("://", 1)[1]:
            raise ValueError(f'"{o}" isn\'t an origin — use the form https://example.com')
        out.append(o)
    return list(dict.fromkeys(out))


class KeyIn(BaseModel):
    name: str = Field(default="Public key", min_length=1, max_length=120)
    # None = always the latest saved version.
    version: int | None = Field(default=None, ge=1)
    allowed_origins: list[str] = Field(default_factory=list, max_length=20)
    requests_per_minute: int = Field(default=20, ge=1, le=600)
    daily_quota: int | None = Field(default=None, ge=1, le=1_000_000)
    acknowledge_write_tools: bool = False
    share: bool = False
    per_user_daily_limit: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: list[str]) -> list[str]:
        return _clean_origins(value)


class KeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "paused"] | None = None
    version: int | None = Field(default=None, ge=1)
    latest: bool = False  # follow the latest saved version from now on
    allowed_origins: list[str] | None = None
    requests_per_minute: int | None = Field(default=None, ge=1, le=600)
    daily_quota: int | None = Field(default=None, ge=1, le=1_000_000)
    no_daily_quota: bool = False
    share: bool | None = None
    per_user_daily_limit: int | None = Field(default=None, ge=1, le=10_000)
    no_per_user_limit: bool = False

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_origins(value)


class KeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    status: str
    version: int | None
    allowed_origins: list[str]
    requests_per_minute: int
    daily_quota: int | None
    runs_today: int
    last_used_at: datetime | None
    created_at: datetime
    owner_id: str
    is_mine: bool
    share_enabled: bool
    share_slug: str | None
    tool_mode: str
    per_user_daily_limit: int | None


class KeyCreated(KeyOut):
    key: str


async def _target(db: AsyncSession, kind: Kind, target_id: str, user: CurrentUser) -> BuilderAgent | BuilderWorkflow:
    target = await get_agent(db, target_id, user) if kind == "agents" else await _get_workflow(db, target_id, user)
    if not can_manage(target.owner_id, user):
        raise HTTPException(status_code=403, detail="Only its creator or a tenant admin can publish it.")
    return target


async def _out(db: AsyncSession, key: BuilderPublicKey, user: CurrentUser) -> dict:
    return {
        "id": key.id, "name": key.name, "key_prefix": key.key_prefix, "status": key.status, "version": key.version,
        "allowed_origins": key.allowed_origins or [], "requests_per_minute": key.requests_per_minute,
        "daily_quota": key.daily_quota, "runs_today": await usage(db, key.id, start_of_day(utcnow())),
        "last_used_at": as_utc(key.last_used_at), "created_at": as_utc(key.created_at), "owner_id": key.owner_id,
        "is_mine": key.owner_id == user.id, "share_enabled": bool(key.share_enabled), "share_slug": key.share_slug,
        "tool_mode": key.tool_mode or "publisher", "per_user_daily_limit": key.per_user_daily_limit,
    }


async def _check_version(db: AsyncSession, kind: Kind, target, version: int | None) -> None:
    if version is None or version == target.version:
        return
    column = BuilderVersion.agent_id if kind == "agents" else BuilderVersion.workflow_id
    exists = (await db.execute(select(BuilderVersion.id).where(column == target.id, BuilderVersion.version == version))).first()
    if not exists:
        raise HTTPException(status_code=422, detail=f"There's no saved version {version} to publish.")


@router.get("/{kind}/{target_id}/publish-check")
async def publish_check(kind: Kind, target_id: str, version: int | None = None, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    await _check_version(db, kind, target, version)
    try:
        definition, resolved = await definition_for(db, kind[:-1], target, version)
    except PublishError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    agents = [definition["agent"]] if "agent" in definition else list((definition.get("agents") or {}).values())
    advice = []
    if any(not AgentConfig.model_validate(a.get("config") or {}).guardrails.injection for a in agents):
        advice.append("Turn on “Refuse requests that try to override its instructions” — anyone with the key can send it anything.")
    return {
        "version": resolved,
        "write_tools": await write_tools(db, definition),
        "problems": await definition_problems(db, user, definition, {}),
        "advice": advice,
    }


@router.get("/{kind}/{target_id}/public-keys", response_model=list[KeyOut])
async def list_keys(kind: Kind, target_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    column = BuilderPublicKey.agent_id if kind == "agents" else BuilderPublicKey.workflow_id
    keys = (await db.execute(select(BuilderPublicKey).where(column == target.id).order_by(BuilderPublicKey.created_at.desc()))).scalars().all()
    return [KeyOut(**await _out(db, k, user)) for k in keys]


@router.post("/{kind}/{target_id}/public-keys", response_model=KeyCreated, status_code=201)
async def create_key(kind: Kind, target_id: str, payload: KeyIn, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    target = await _target(db, kind, target_id, user)
    await _check_version(db, kind, target, payload.version)
    definition, _ = await definition_for(db, kind[:-1], target, payload.version)
    exposed = await write_tools(db, definition)
    if exposed and not payload.acknowledge_write_tools:
        raise HTTPException(status_code=409, detail={
            "message": "Callers could make it use tools that change data, with your accounts. Confirm to publish anyway.",
            "write_tools": exposed,
        })
    secret, digest, prefix = new_key()
    key = BuilderPublicKey(
        tenant_id=target.tenant_id, owner_id=user.id, kind=kind[:-1], name=payload.name.strip(), key_hash=digest,
        key_prefix=prefix, status="active", version=payload.version, allowed_origins=payload.allowed_origins,
        requests_per_minute=payload.requests_per_minute, daily_quota=payload.daily_quota,
        share_enabled=payload.share, share_slug=new_share_slug() if payload.share else None,
        per_user_daily_limit=payload.per_user_daily_limit,
        **({"agent_id": target.id} if kind == "agents" else {"workflow_id": target.id}),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return KeyCreated(**await _out(db, key, user), key=secret)


async def _key(db: AsyncSession, key_id: str, user: CurrentUser) -> BuilderPublicKey:
    key = (
        await db.execute(select(BuilderPublicKey).where(BuilderPublicKey.id == key_id, BuilderPublicKey.tenant_id == user.tenant_id))
    ).scalars().first()
    if key is None or key.status == "revoked":
        raise HTTPException(status_code=404, detail="Key not found.")
    await _target(db, "agents" if key.kind == "agent" else "workflows", key.agent_id or key.workflow_id, user)
    return key


@router.patch("/public-keys/{key_id}", response_model=KeyOut)
async def update_key(key_id: str, payload: KeyUpdate, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    key = await _key(db, key_id, user)
    kind: Kind = "agents" if key.kind == "agent" else "workflows"
    target = await _target(db, kind, key.agent_id or key.workflow_id, user)
    if payload.latest:
        key.version = None
    elif payload.version is not None:
        await _check_version(db, kind, target, payload.version)
        key.version = payload.version
    if payload.share is not None:
        key.share_enabled = payload.share
        if payload.share and not key.share_slug:
            key.share_slug = new_share_slug()
    for field in ("name", "status", "allowed_origins", "requests_per_minute", "daily_quota", "per_user_daily_limit"):
        value = getattr(payload, field)
        if value is not None:
            setattr(key, field, value.strip() if isinstance(value, str) else value)
    if payload.no_daily_quota:
        key.daily_quota = None
    if payload.no_per_user_limit:
        key.per_user_daily_limit = None
    await db.commit()
    await db.refresh(key)
    return KeyOut(**await _out(db, key, user))


@router.delete("/public-keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    key = await _key(db, key_id, user)
    key.status = "revoked"
    await db.commit()


class PublishedKey(KeyOut):
    kind: str
    target_id: str
    target_name: str
    requests: int  # in the window


class PublishedDay(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    success: int
    error: int


class PublishedStats(BaseModel):
    live_keys: int
    total_requests: int
    success_rate: float  # of the finished ones, 0–1
    avg_latency_ms: int  # of the finished ones


class PublishedOut(BaseModel):
    days: int
    stats: PublishedStats
    series: list[PublishedDay]
    keys: list[PublishedKey]


@router.get("/published", response_model=PublishedOut)
async def published(days: int = 14, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    """The caller's publishing at a glance: their keys on every agent and
    workflow (revoked ones are gone from the list but their calls still count),
    and the public calls of the last ``days`` days."""
    days = max(1, min(days, 90))
    today = start_of_day(utcnow())
    since = today - timedelta(days=days - 1)

    keys = (
        await db.execute(
            select(BuilderPublicKey)
            .where(BuilderPublicKey.owner_id == user.id, BuilderPublicKey.tenant_id == user.tenant_id)
            .order_by(BuilderPublicKey.created_at.desc())
        )
    ).scalars().all()
    rows = (
        await db.execute(
            select(BuilderRun.public_key_id, BuilderRun.status, BuilderRun.created_at, BuilderRun.started_at, BuilderRun.finished_at)
            .where(BuilderRun.public_key_id.in_([k.id for k in keys] or [""]), BuilderRun.created_at >= since)
        )
    ).all()

    per_day = {(since + timedelta(days=i)).date().isoformat(): [0, 0] for i in range(days)}
    per_key: dict[str, int] = {}
    ok = finished = 0
    latency: list[float] = []
    for key_id, status, created, started, ended in rows:
        per_key[key_id] = per_key.get(key_id, 0) + 1
        if status not in states.TERMINAL:
            continue
        finished += 1
        bucket = per_day.get(as_utc(created).date().isoformat())
        if status == states.SUCCEEDED:
            ok += 1
            if bucket:
                bucket[0] += 1
        elif bucket:
            bucket[1] += 1
        if started and ended:
            latency.append((as_utc(ended) - as_utc(started)).total_seconds() * 1000)

    names: dict[str, str] = {}
    agent_ids = [k.agent_id for k in keys if k.agent_id]
    workflow_ids = [k.workflow_id for k in keys if k.workflow_id]
    if agent_ids:
        names.update((await db.execute(select(BuilderAgent.id, BuilderAgent.name).where(BuilderAgent.id.in_(agent_ids)))).tuples().all())
    if workflow_ids:
        names.update((await db.execute(select(BuilderWorkflow.id, BuilderWorkflow.name).where(BuilderWorkflow.id.in_(workflow_ids)))).tuples().all())

    listed = []
    for k in keys:
        if k.status == "revoked":
            continue
        target_id = k.agent_id or k.workflow_id or ""
        listed.append(PublishedKey(
            **await _out(db, k, user), kind=k.kind, target_id=target_id,
            target_name=names.get(target_id, "Deleted"), requests=per_key.get(k.id, 0),
        ))

    return PublishedOut(
        days=days,
        stats=PublishedStats(
            live_keys=sum(1 for k in keys if k.status == "active"),
            total_requests=len(rows),
            success_rate=round(ok / finished, 4) if finished else 0.0,
            avg_latency_ms=round(sum(latency) / len(latency)) if latency else 0,
        ),
        series=[PublishedDay(date=d, success=v[0], error=v[1]) for d, v in per_day.items()],
        keys=listed,
    )
