"""What a person's runs cost this month, and their own monthly limit.

Costs are the estimates every run already records (``builder.pricing``); a run
whose model has no known price adds nothing and is counted as unpriced. The
month is the calendar month in UTC.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from builder.models import BuilderRun, BuilderSpendLimit
from builder.runs.db import as_utc, utcnow

# Shown as "close to the limit" from here on.
WARN_AT = 0.8


def month_start(now: datetime | None = None) -> datetime:
    now = as_utc(now or utcnow())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(now: datetime | None = None) -> datetime:
    start = month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def previous_month(now: datetime | None = None) -> datetime:
    start = month_start(now)
    return start.replace(year=start.year - 1, month=12) if start.month == 1 else start.replace(month=start.month - 1)


async def spent(db: AsyncSession, owner_id: str, since: datetime, until: datetime | None = None) -> float:
    query = select(func.coalesce(func.sum(BuilderRun.cost_usd), 0.0)).where(BuilderRun.owner_id == owner_id, BuilderRun.created_at >= since)
    if until is not None:
        query = query.where(BuilderRun.created_at < until)
    return round(float((await db.execute(query)).scalar_one() or 0.0), 6)


async def monthly_limit(db: AsyncSession, owner_id: str) -> float | None:
    row = await db.get(BuilderSpendLimit, owner_id)
    return row.monthly_usd if row else None


async def over_limit(db: AsyncSession, owner_id: str, now: datetime | None = None) -> str | None:
    """Why a new run can't start (this month's limit is used up), or None."""
    limit = await monthly_limit(db, owner_id)
    if limit is None:
        return None
    used = await spent(db, owner_id, month_start(now))
    if used < limit:
        return None
    resets = next_month(now).strftime("%-d %b")
    return (
        f"Your monthly limit of ${limit:.2f} is used up (${used:.2f} spent this month). "
        f"Runs start again on {resets}, or raise the limit on the Dashboard."
    )


__all__ = ["WARN_AT", "month_start", "monthly_limit", "next_month", "over_limit", "previous_month", "spent"]
