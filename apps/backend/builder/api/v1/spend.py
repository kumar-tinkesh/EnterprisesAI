"""What your runs cost this month, and your own monthly limit (mounted under ``/api/v1/builder``).

    GET /spend          this month so far: total, by day, by agent/workflow, last month, the limit
    PUT /spend/limit    {"monthly_usd": 5} sets it; null removes it

Every run you start counts (chat, Run, schedules, webhooks, tests), whatever
it ran. The figures are estimates from token counts (``builder.pricing``).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.db.session import get_db

from builder.api.v1.deps import get_end_user
from builder.models import BuilderAgent, BuilderRun, BuilderSpendLimit, BuilderWorkflow
from builder.runs.db import as_utc, utcnow
from builder.spend import WARN_AT, month_start, monthly_limit, next_month, previous_month, spent

router = APIRouter()


class SpendDay(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    cost_usd: float


class SpendItem(BaseModel):
    kind: str
    id: str
    name: str
    exists: bool
    runs: int
    cost_usd: float


class SpendOut(BaseModel):
    month_start: str  # YYYY-MM-DD
    resets_on: str  # YYYY-MM-DD, the 1st of next month
    spent_usd: float
    last_month_usd: float
    runs: int
    # Runs with tokens but no known price for their model (not in spent_usd).
    unpriced_runs: int
    limit_usd: float | None
    # "ok" | "near" (80%+) | "over" (new runs wait)
    status: str
    daily: list[SpendDay]
    by_item: list[SpendItem]


class LimitIn(BaseModel):
    monthly_usd: float | None = Field(default=None, gt=0, le=100_000)


async def _summary(db: AsyncSession, user: CurrentUser) -> SpendOut:
    now = utcnow()
    start = month_start(now)
    rows = (
        await db.execute(
            select(
                BuilderRun.kind, BuilderRun.agent_id, BuilderRun.workflow_id, BuilderRun.cost_usd,
                BuilderRun.prompt_tokens, BuilderRun.completion_tokens, BuilderRun.created_at, BuilderRun.definition,
            ).where(BuilderRun.owner_id == user.id, BuilderRun.created_at >= start)
        )
    ).all()

    days = (as_utc(now).date() - start.date()).days + 1
    daily = {(start + timedelta(days=i)).date().isoformat(): 0.0 for i in range(days)}
    items: dict[tuple[str, str], list] = {}
    for r in rows:
        key = as_utc(r.created_at).date().isoformat()
        if key in daily:
            daily[key] = round(daily[key] + (r.cost_usd or 0.0), 6)
        target = r.workflow_id if r.kind == "workflow" else r.agent_id
        if not target:
            continue
        it = items.setdefault((r.kind, target), [0, 0.0, None])
        it[0] += 1
        it[1] = round(it[1] + (r.cost_usd or 0.0), 6)
        it[2] = it[2] or ((r.definition or {}).get(r.kind) or {}).get("name")

    names: dict[str, str] = {}
    agent_ids = [t for (k, t) in items if k == "agent"]
    workflow_ids = [t for (k, t) in items if k == "workflow"]
    if agent_ids:
        names.update((await db.execute(select(BuilderAgent.id, BuilderAgent.name).where(BuilderAgent.id.in_(agent_ids)))).tuples().all())
    if workflow_ids:
        names.update((await db.execute(select(BuilderWorkflow.id, BuilderWorkflow.name).where(BuilderWorkflow.id.in_(workflow_ids)))).tuples().all())

    total = round(sum(r.cost_usd or 0.0 for r in rows), 6)
    limit = await monthly_limit(db, user.id)
    status = "ok" if limit is None or total < limit * WARN_AT else "near" if total < limit else "over"
    top = sorted(items.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))[:6]
    return SpendOut(
        month_start=start.date().isoformat(),
        resets_on=next_month(now).date().isoformat(),
        spent_usd=total,
        last_month_usd=await spent(db, user.id, previous_month(now), start),
        runs=len(rows),
        unpriced_runs=sum(1 for r in rows if r.cost_usd is None and (r.prompt_tokens or r.completion_tokens)),
        limit_usd=limit,
        status=status,
        daily=[SpendDay(date=d, cost_usd=c) for d, c in daily.items()],
        by_item=[
            SpendItem(kind=k, id=t, name=names.get(t) or v[2] or f"Deleted {k}", exists=t in names, runs=v[0], cost_usd=v[1])
            for (k, t), v in top
        ],
    )


@router.get("/spend", response_model=SpendOut)
async def get_spend(user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    return await _summary(db, user)


@router.put("/spend/limit", response_model=SpendOut)
async def set_limit(payload: LimitIn, user: CurrentUser = Depends(get_end_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(BuilderSpendLimit, user.id)
    if payload.monthly_usd is None:
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(BuilderSpendLimit(owner_id=user.id, tenant_id=user.tenant_id, monthly_usd=round(payload.monthly_usd, 2)))
    else:
        row.monthly_usd = round(payload.monthly_usd, 2)
    await db.commit()
    return await _summary(db, user)
