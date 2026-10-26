"""Dashboard numbers (mounted under ``/api/v1/builder``).

    GET /insights?days=7    the caller's runs: this window vs the one before,
                            a daily series over two windows, busiest agents, all-time totals
    GET /overview?days=7    one line per agent/workflow the caller can see (the Executions
                            list): its runs per day, last run, what's live, health, schedule, keys

Counts the caller's own runs (purpose "run": chats, the playground,
schedules). Test-case runs and public-key calls have their own views.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.deps import get_end_user
from builder.api.v1.health import compute_health
from builder.models import BuilderAgent, BuilderPublicKey, BuilderRun, BuilderSchedule, BuilderWorkflow
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


class OverviewItem(BaseModel):
    kind: str
    id: str
    runs: int  # in the window
    succeeded: int
    failed: int
    daily: list[int]  # runs per day, oldest first
    last_run_at: datetime | None
    last_status: str | None
    running: int  # queued or running now
    waiting: int  # waiting for a person
    health_status: str
    health_score: int | None
    schedule: str | None  # its cron, when an enabled schedule exists
    next_run_at: datetime | None
    published: int  # live publishable keys


class OverviewTotals(BaseModel):
    runs: int
    succeeded: int
    failed: int
    running: int
    waiting: int


class OverviewOut(BaseModel):
    days: int
    totals: OverviewTotals
    items: list[OverviewItem]


@router.get("/overview", response_model=OverviewOut)
async def overview(
    days: int = Query(default=7, ge=1, le=30),
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    agents = (await db.execute(
        select(BuilderAgent).where(BuilderAgent.tenant_id == user.tenant_id, BuilderAgent.workflow_id.is_(None)).limit(200)
    )).scalars().all()
    workflows = (await db.execute(select(BuilderWorkflow).where(BuilderWorkflow.tenant_id == user.tenant_id).limit(200))).scalars().all()
    targets = [("agent", a) for a in agents] + [("workflow", w) for w in workflows]

    since = start_of_day(utcnow()) - timedelta(days=days - 1)
    rows = (await db.execute(
        select(BuilderRun.kind, BuilderRun.agent_id, BuilderRun.workflow_id, BuilderRun.status, BuilderRun.created_at)
        .where(BuilderRun.owner_id == user.id, BuilderRun.purpose == "run")
    )).all()
    live = {states.QUEUED, states.RUNNING}
    per: dict[tuple[str, str], dict] = {}
    for r in rows:
        target = r.workflow_id if r.kind == "workflow" else r.agent_id
        if not target:
            continue
        p = per.setdefault((r.kind, target), {"runs": 0, "ok": 0, "bad": 0, "daily": [0] * days, "last": None, "last_status": None, "running": 0, "waiting": 0})
        created = as_utc(r.created_at)
        if p["last"] is None or created > p["last"]:
            p["last"], p["last_status"] = created, r.status
        p["running"] += r.status in live
        p["waiting"] += r.status == states.WAITING
        if created >= since:
            p["runs"] += 1
            p["ok"] += r.status == states.SUCCEEDED
            p["bad"] += r.status == states.FAILED
            p["daily"][min(days - 1, (created - since).days)] += 1

    schedules = {
        (s.kind, s.agent_id or s.workflow_id): s
        for s in (await db.execute(select(BuilderSchedule).where(BuilderSchedule.tenant_id == user.tenant_id, BuilderSchedule.enabled.is_(True)))).scalars()
    }
    keys: dict[str, int] = {}
    for k in (await db.execute(select(BuilderPublicKey).where(BuilderPublicKey.tenant_id == user.tenant_id, BuilderPublicKey.status == "active"))).scalars():
        keys[k.agent_id or k.workflow_id or ""] = keys.get(k.agent_id or k.workflow_id or "", 0) + 1

    items = []
    for kind, t in targets:
        p = per.get((kind, t.id)) or {"runs": 0, "ok": 0, "bad": 0, "daily": [0] * days, "last": None, "last_status": None, "running": 0, "waiting": 0}
        h = await compute_health(db, user, t)
        sched = schedules.get((kind, t.id))
        items.append(OverviewItem(
            kind=kind, id=t.id, runs=p["runs"], succeeded=p["ok"], failed=p["bad"], daily=p["daily"],
            last_run_at=p["last"], last_status=p["last_status"], running=p["running"], waiting=p["waiting"],
            health_status=h.status, health_score=h.score,
            schedule=sched.cron if sched else None, next_run_at=as_utc(sched.next_run_at) if sched else None,
            published=keys.get(t.id, 0),
        ))
    return OverviewOut(
        days=days,
        totals=OverviewTotals(
            runs=sum(i.runs for i in items), succeeded=sum(i.succeeded for i in items), failed=sum(i.failed for i in items),
            running=sum(i.running for i in items), waiting=sum(i.waiting for i in items),
        ),
        items=items,
    )
