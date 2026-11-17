"""What an agent or workflow has used (mounted under ``/api/v1/builder``).

    GET /agents/{agent_id}/usage?days=30
    GET /workflows/{workflow_id}/usage?days=30

Runs, tokens and estimated cost (``builder.pricing``) over the window, with a
daily series. Its owner (or a tenant admin) sees everyone's runs added up —
numbers only, never what was asked; anyone else sees their own.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.agents import get_agent
from builder.api.v1.deps import can_manage, get_end_user
from builder.models import BuilderRun
from builder.publishing.service import start_of_day
from builder.runs import states
from builder.runs.db import as_utc, utcnow

router = APIRouter()


class UsageDay(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    runs: int
    succeeded: int
    failed: int
    tokens: int
    cost_usd: float


class UsageOut(BaseModel):
    # "everyone" (its manager) or "mine"
    scope: str
    days: int
    runs: int
    succeeded: int
    failed: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    # Runs with tokens but no price for their model (their cost isn't in cost_usd).
    unpriced_runs: int
    avg_cost_usd: float | None
    avg_seconds: float | None
    # run | test | public, how many of each
    by_purpose: dict[str, int]
    daily: list[UsageDay]


def summarize(rows: list[BuilderRun], *, days: int, scope: str) -> UsageOut:
    today = start_of_day(utcnow())
    daily = {(today - timedelta(days=i)).date().isoformat(): UsageDay(date="", runs=0, succeeded=0, failed=0, tokens=0, cost_usd=0.0) for i in range(days)}
    for key, day in daily.items():
        day.date = key
    priced = [r for r in rows if r.cost_usd is not None]
    durations = [
        (as_utc(r.finished_at) - as_utc(r.started_at)).total_seconds()
        for r in rows if r.status in states.TERMINAL and r.started_at and r.finished_at
    ]
    by_purpose: dict[str, int] = {}
    for r in rows:
        by_purpose[r.purpose or "run"] = by_purpose.get(r.purpose or "run", 0) + 1
        day = daily.get(as_utc(r.created_at).date().isoformat())
        if day:
            day.runs += 1
            day.succeeded += r.status == states.SUCCEEDED
            day.failed += r.status == states.FAILED
            day.tokens += (r.prompt_tokens or 0) + (r.completion_tokens or 0)
            day.cost_usd = round(day.cost_usd + (r.cost_usd or 0.0), 6)
    total = round(sum(r.cost_usd for r in priced), 6)
    return UsageOut(
        scope=scope,
        days=days,
        runs=len(rows),
        succeeded=sum(1 for r in rows if r.status == states.SUCCEEDED),
        failed=sum(1 for r in rows if r.status == states.FAILED),
        prompt_tokens=sum(r.prompt_tokens or 0 for r in rows),
        completion_tokens=sum(r.completion_tokens or 0 for r in rows),
        cost_usd=total,
        unpriced_runs=sum(1 for r in rows if r.cost_usd is None and (r.prompt_tokens or r.completion_tokens)),
        avg_cost_usd=round(total / len(priced), 6) if priced else None,
        avg_seconds=round(sum(durations) / len(durations), 2) if durations else None,
        by_purpose=by_purpose,
        daily=sorted(daily.values(), key=lambda d: d.date),
    )


async def _usage(db: AsyncSession, user: CurrentUser, column, target_id: str, owner_id: str, days: int) -> UsageOut:
    everyone = can_manage(owner_id, user)
    since = start_of_day(utcnow()) - timedelta(days=days - 1)
    query = select(BuilderRun).where(BuilderRun.tenant_id == user.tenant_id, column == target_id, BuilderRun.created_at >= since)
    if not everyone:
        query = query.where(BuilderRun.owner_id == user.id)
    rows = list((await db.execute(query)).scalars())
    return summarize(rows, days=days, scope="everyone" if everyone else "mine")


@router.get("/agents/{agent_id}/usage", response_model=UsageOut)
async def agent_usage(
    agent_id: str,
    days: int = Query(default=30, ge=1, le=90),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id, user)
    return await _usage(db, user, BuilderRun.agent_id, agent.id, agent.owner_id, days)


@router.get("/workflows/{workflow_id}/usage", response_model=UsageOut)
async def workflow_usage(
    workflow_id: str,
    days: int = Query(default=30, ge=1, le=90),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    from builder.api.v1.workflows import _get_workflow

    workflow = await _get_workflow(db, workflow_id, user)
    return await _usage(db, user, BuilderRun.workflow_id, workflow.id, workflow.owner_id, days)
