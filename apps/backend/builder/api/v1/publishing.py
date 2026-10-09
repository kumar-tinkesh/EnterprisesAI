"""Publishing (mounted at ``/api/v1/builder``): publishable keys for an agent or workflow.

    GET    /{agents|workflows}/{id}/publish-check   what publishing would expose: write tools, problems, advice
    GET    /{agents|workflows}/{id}/public-keys     its keys (with today's use)
    POST   /{agents|workflows}/{id}/public-keys     make one — the key is in the response, once
    PATCH  /public-keys/{key_id}                    pause/resume, move to another version, limits, origins
    DELETE /public-keys/{key_id}                    revoke (it stops working at once; the record stays)

Publishing is for the agent's/workflow's creator or a tenant admin. A key
runs as whoever made it, with their connected tools — so when callers could
make it use tools that change data, the maker has to say yes to that
explicitly (``acknowledge_write_tools``).
"""
from __future__ import annotations

from datetime import datetime
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
from builder.models import BuilderAgent, BuilderPublicKey, BuilderVersion, BuilderWorkflow
from builder.publishing.service import (
    PublishError, definition_for, definition_problems, new_key, start_of_day, usage, write_tools,
)
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
        "is_mine": key.owner_id == user.id,
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
    for field in ("name", "status", "allowed_origins", "requests_per_minute", "daily_quota"):
        value = getattr(payload, field)
        if value is not None:
            setattr(key, field, value.strip() if isinstance(value, str) else value)
    if payload.no_daily_quota:
        key.daily_quota = None
    await db.commit()
    await db.refresh(key)
    return KeyOut(**await _out(db, key, user))


@router.delete("/public-keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    key = await _key(db, key_id, user)
    key.status = "revoked"
    await db.commit()
