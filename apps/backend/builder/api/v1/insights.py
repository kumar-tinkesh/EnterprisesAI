"""Dashboard numbers (mounted under ``/api/v1/builder``).

    GET /insights?days=7    the caller's runs: this window vs the one before,
                            a daily series over two windows, busiest agents, all-time totals

Counts the caller's own runs (purpose "run": chats, the playground,
schedules). Test-case runs and public-key calls have their own views.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.deps import get_end_user
from builder.models import BuilderAgent, BuilderRun, BuilderWorkflow
from builder.publishing.service import start_of_day
from builder.runs import states
from builder.runs.db import as_utc, utcnow

router = APIRouter()


class Window(BaseModel):
    runs: int
    succeeded: int
    failed: int
    success_rate: float  # of the finished ones, 0–1
    avg_latency_ms: int  # of the finished ones that started
    active: int  # distinct agents/workflows that ran


class Day(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    succeeded: int
    failed: int


class Busiest(BaseModel):
    kind: str
    id: str
    name: str
    exists: bool
    runs: int
    succeeded: int


class AllTime(BaseModel):
    runs: int
    success_rate: float


class InsightsOut(BaseModel):
    days: int
    current: Window
    previous: Window
    series: list[Day]
    busiest: list[Busiest]
    all_time: AllTime


def _window(rows: list) -> Window:
    finished = [r for r in rows if r.status in states.TERMINAL]
    ok = sum(1 for r in finished if r.status == states.SUCCEEDED)
    latency = [
        (as_utc(r.finished_at) - as_utc(r.started_at)).total_seconds() * 1000
        for r in finished if r.started_at and r.finished_at
    ]
    return Window(
        runs=len(rows),
        succeeded=ok,
        failed=sum(1 for r in finished if r.status == states.FAILED),
        success_rate=round(ok / len(finished), 4) if finished else 0.0,
        avg_latency_ms=round(sum(latency) / len(latency)) if latency else 0,
        active=len({(r.kind, r.workflow_id if r.kind == "workflow" else r.agent_id) for r in rows}),
    )


@router.get("/insights", response_model=InsightsOut)
async def insights(
    days: int = Query(default=7, ge=1, le=90),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(
                BuilderRun.kind, BuilderRun.agent_id, BuilderRun.workflow_id, BuilderRun.status,
                BuilderRun.created_at, BuilderRun.started_at, BuilderRun.finished_at, BuilderRun.definition,
            ).where(BuilderRun.owner_id == user.id, BuilderRun.purpose == "run")
        )
    ).all()

    today = start_of_day(utcnow())
    cur_start = today - timedelta(days=days - 1)
    prev_start = cur_start - timedelta(days=days)
    current = [r for r in rows if as_utc(r.created_at) >= cur_start]
    previous = [r for r in rows if prev_start <= as_utc(r.created_at) < cur_start]

    # Two windows of days, so the chart shows the comparison the tiles make.
    per_day = {(prev_start + timedelta(days=i)).date().isoformat(): [0, 0] for i in range(days * 2)}
    for r in rows:
        bucket = per_day.get(as_utc(r.created_at).date().isoformat())
        if bucket is None:
            continue
        if r.status == states.SUCCEEDED:
            bucket[0] += 1
        elif r.status == states.FAILED:
            bucket[1] += 1

    counts: dict[tuple[str, str], list] = {}
    for r in rows:
        target = r.workflow_id if r.kind == "workflow" else r.agent_id
        if not target:
            continue
        c = counts.setdefault((r.kind, target), [0, 0, None])
        c[0] += 1
        c[1] += r.status == states.SUCCEEDED
        # The name it had when it ran, for ones deleted since.
        c[2] = c[2] or ((r.definition or {}).get(r.kind) or {}).get("name")
    top = sorted(counts.items(), key=lambda kv: -kv[1][0])[:5]
    agent_ids = [t for (k, t), _ in top if k == "agent"]
    workflow_ids = [t for (k, t), _ in top if k == "workflow"]
    names: dict[str, str] = {}
    if agent_ids:
        names.update((await db.execute(select(BuilderAgent.id, BuilderAgent.name).where(BuilderAgent.id.in_(agent_ids)))).tuples().all())
    if workflow_ids:
        names.update((await db.execute(select(BuilderWorkflow.id, BuilderWorkflow.name).where(BuilderWorkflow.id.in_(workflow_ids)))).tuples().all())

    finished = [r for r in rows if r.status in states.TERMINAL]
    return InsightsOut(
        days=days,
        current=_window(current),
        previous=_window(previous),
        series=[Day(date=d, succeeded=v[0], failed=v[1]) for d, v in per_day.items()],
        busiest=[
            Busiest(
                kind=kind, id=target, name=names.get(target) or c[2] or f"Deleted {kind}",
                exists=target in names, runs=c[0], succeeded=c[1],
            )
            for (kind, target), c in top
        ],
        all_time=AllTime(
            runs=len(rows),
            success_rate=round(sum(1 for r in finished if r.status == states.SUCCEEDED) / len(finished), 4) if finished else 0.0,
        ),
    )
