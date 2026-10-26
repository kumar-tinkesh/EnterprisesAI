"""Schedules (mounted at ``/api/v1/builder/schedules``).

    GET    ""                 schedules of an agent or workflow (?agent_id= | ?workflow_id=), or mine
    POST   ""                 schedule an agent (a workflow is scheduled by its Schedule trigger step)
    POST   /preview           check a cron + timezone: in words, and the next few times
    PATCH  /{schedule_id}     change an agent schedule (cron, timezone, request, on/off)
    DELETE /{schedule_id}
    POST   /{schedule_id}/run start it now, once (same checks; doesn't move the next time)

A schedule runs as the person who set it, with their own connected tools, so
only they change or delete it. A workflow's schedule lives on its Schedule
trigger step: change it there (saving the workflow keeps this in sync).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.agents import get_agent
from builder.api.v1.deps import get_end_user
from builder.models import BuilderSchedule
from builder.runs.db import as_utc, utcnow
from builder.schedules.cron import ScheduleError, describe, upcoming, validate
from builder.schedules.service import STARTED, apply_timing, start_scheduled_run

router = APIRouter()


class ScheduleOut(BaseModel):
    id: str
    kind: str
    agent_id: str | None
    workflow_id: str | None
    node_id: str | None
    cron: str
    timezone: str
    description: str
    input: dict[str, Any]
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_id: str | None
    last_status: str | None
    last_error: str | None
    owner_id: str
    is_mine: bool
    # Agent schedules are edited here; a workflow's on its Schedule step.
    editable: bool
    created_at: datetime


class ScheduleCreate(BaseModel):
    agent_id: str
    cron: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", max_length=64)
    input: str = Field(default="", max_length=20_000)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    cron: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = Field(default=None, max_length=64)
    input: str | None = Field(default=None, max_length=20_000)
    enabled: bool | None = None


class PreviewRequest(BaseModel):
    cron: str = Field(max_length=100)
    timezone: str = Field(default="UTC", max_length=64)


class PreviewOut(BaseModel):
    ok: bool
    error: str | None = None
    description: str = ""
    next_runs: list[datetime] = Field(default_factory=list)


def _out(s: BuilderSchedule, user: CurrentUser) -> ScheduleOut:
    mine = s.owner_id == user.id
    return ScheduleOut(
        id=s.id, kind=s.kind, agent_id=s.agent_id, workflow_id=s.workflow_id, node_id=s.node_id,
        cron=s.cron, timezone=s.timezone, description=describe(s.cron) if s.cron else "Not set",
        # as_utc: SQLite hands these back without a zone; the browser must see UTC.
        input=s.input or {}, enabled=s.enabled, next_run_at=as_utc(s.next_run_at), last_run_at=as_utc(s.last_run_at),
        last_run_id=s.last_run_id, last_status=s.last_status, last_error=s.last_error,
        owner_id=s.owner_id, is_mine=mine, editable=mine and s.kind == "agent", created_at=as_utc(s.created_at),
    )


def _check(cron: str, tz: str) -> None:
    try:
        validate(cron, tz)
    except ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _get(db: AsyncSession, schedule_id: str, user: CurrentUser) -> BuilderSchedule:
    s = (
        await db.execute(select(BuilderSchedule).where(BuilderSchedule.id == schedule_id, BuilderSchedule.tenant_id == user.tenant_id))
    ).scalars().first()
    if s is None:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return s


def _own(s: BuilderSchedule, user: CurrentUser) -> None:
    if s.owner_id != user.id:
        raise HTTPException(status_code=403, detail="This schedule runs as someone else; only they can change it.")
    if s.kind != "agent":
        raise HTTPException(status_code=409, detail="Change this on the workflow's Schedule step, then save the workflow.")


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(
    agent_id: str | None = None,
    workflow_id: str | None = None,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BuilderSchedule).where(BuilderSchedule.tenant_id == user.tenant_id)
    if agent_id:
        query = query.where(BuilderSchedule.agent_id == agent_id)
    elif workflow_id:
        query = query.where(BuilderSchedule.workflow_id == workflow_id)
    else:
        query = query.where(BuilderSchedule.owner_id == user.id)
    rows = (await db.execute(query.order_by(BuilderSchedule.created_at))).scalars().all()
    return [_out(s, user) for s in rows]


@router.post("/preview", response_model=PreviewOut)
async def preview_schedule(payload: PreviewRequest, user: CurrentUser = Depends(get_end_user)):
    try:
        validate(payload.cron, payload.timezone)
    except ScheduleError as exc:
        return PreviewOut(ok=False, error=str(exc))
    return PreviewOut(ok=True, description=describe(payload.cron.strip()), next_runs=upcoming(payload.cron.strip(), payload.timezone))


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(payload: ScheduleCreate, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    agent = await get_agent(db, payload.agent_id, user)
    if agent.workflow_id:
        raise HTTPException(status_code=409, detail="This agent belongs to a workflow; schedule the workflow instead.")
    _check(payload.cron, payload.timezone)
    s = BuilderSchedule(
        tenant_id=user.tenant_id, owner_id=user.id, kind="agent", agent_id=agent.id,
        cron="", timezone="UTC", enabled=False, input={"text": payload.input, "variables": {}},
    )
    apply_timing(s, cron=payload.cron, tz=payload.timezone, enabled=payload.enabled)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _out(s, user)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: str, payload: ScheduleUpdate, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)
):
    s = await _get(db, schedule_id, user)
    _own(s, user)
    cron = payload.cron if payload.cron is not None else s.cron
    tz = payload.timezone if payload.timezone is not None else s.timezone
    if payload.cron is not None or payload.timezone is not None:
        _check(cron, tz)
    if payload.input is not None:
        s.input = {**(s.input or {}), "text": payload.input}
    apply_timing(s, cron=cron, tz=tz, enabled=s.enabled if payload.enabled is None else payload.enabled)
    await db.commit()
    await db.refresh(s)
    return _out(s, user)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    s = await _get(db, schedule_id, user)
    _own(s, user)
    await db.delete(s)
    await db.commit()


@router.post("/{schedule_id}/run")
async def run_schedule_now(schedule_id: str, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    s = await _get(db, schedule_id, user)
    if s.owner_id != user.id:
        raise HTTPException(status_code=403, detail="This schedule runs as someone else; only they can start it.")
    status, run_id, error = await start_scheduled_run(db, s)
    s.last_status, s.last_run_id, s.last_error, s.last_run_at = status, run_id, error, utcnow()
    await db.commit()
    if status != STARTED:
        raise HTTPException(status_code=422, detail=error or "It couldn't start.")
    return {"run_id": run_id}
