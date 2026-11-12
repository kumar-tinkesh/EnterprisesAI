"""The platform admin's Overview and Accounts (vendor admin only), across every tenant.

    GET /platform/overview?days=14   people (active, new), runs by day, this month's cost,
                                     the most used apps and the busiest accounts
    GET /platform/accounts/{tenant_id}  one account: its members, the apps they connected,
                                     this month's runs and cost, when it was last active

Counts and names only — never what anyone asked an agent, or any credential.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles
from src.db.session import get_db
from src.models import User
from src.models.auth import AuditEvent
from src.models.tenant import Tenant

from vendor.models import VendorMCPCredential, VendorMCPServer

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))

# What counts as someone being around: signing in, or their session renewing while they use the app.
_PRESENCE = ("login", "sso_login", "refresh_token")


class Pair(BaseModel):
    current: float
    previous: float


class RunDay(BaseModel):
    date: str
    succeeded: int
    failed: int


class WeekCount(BaseModel):
    week_start: str
    count: int


class TopApp(BaseModel):
    id: str
    name: str
    people: int
    tool_calls: int


class TopAccount(BaseModel):
    id: str
    name: str
    is_personal: bool
    runs: int
    cost_usd: float


class Overview(BaseModel):
    days: int
    people_total: int
    active_people: Pair  # distinct people around in the window vs the one before
    new_people: Pair
    runs: Pair
    failed_runs: Pair
    cost_month_usd: float
    cost_last_month_usd: float
    run_days: list[RunDay]  # 2 x days, oldest first
    signups_by_week: list[WeekCount]  # last 8 weeks
    top_apps: list[TopApp]
    top_accounts: list[TopAccount]


class Member(BaseModel):
    id: str
    name: str
    email: str
    role: str
    is_active: bool
    joined: datetime


class AccountApp(BaseModel):
    id: str
    name: str
    people: int


class AccountDetail(BaseModel):
    id: str
    name: str
    is_personal: bool
    status: str
    created_at: datetime
    members: list[Member]
    apps: list[AccountApp]
    runs_month: int
    failed_month: int
    cost_month_usd: float
    last_active: datetime | None


def _start_of_day(t: datetime) -> datetime:
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(t: datetime) -> datetime:
    return _start_of_day(t).replace(day=1)


async def _scalar(db: AsyncSession, query) -> float:
    return float((await db.execute(query)).scalar_one() or 0)


@router.get("/platform/overview", response_model=Overview)
async def platform_overview(
    days: int = Query(default=14, ge=1, le=90), _user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)
):
    from builder.models import BuilderRun, BuilderToolCall
    from builder.runs.db import as_utc, utcnow

    now = utcnow()
    today = _start_of_day(now)
    cur = today - timedelta(days=days - 1)
    prev = cur - timedelta(days=days)
    month = _month_start(now)
    last_month = (month - timedelta(days=1)).replace(day=1)

    async def active(since: datetime, until: datetime | None) -> int:
        q = select(func.count(func.distinct(AuditEvent.user_id))).where(
            AuditEvent.action.in_(_PRESENCE), AuditEvent.user_id.is_not(None), AuditEvent.created_at >= since
        )
        if until is not None:
            q = q.where(AuditEvent.created_at < until)
        return int(await _scalar(db, q))

    async def joined(since: datetime, until: datetime | None) -> int:
        q = select(func.count()).select_from(User).where(User.created_at >= since)
        if until is not None:
            q = q.where(User.created_at < until)
        return int(await _scalar(db, q))

    runs = (
        await db.execute(
            select(BuilderRun.status, BuilderRun.created_at, BuilderRun.tenant_id).where(BuilderRun.created_at >= min(prev, last_month))
        )
    ).all()
    per_day = {(prev + timedelta(days=i)).date().isoformat(): [0, 0] for i in range(days * 2)}
    cur_runs = prev_runs = cur_failed = prev_failed = 0
    for st, created, _tenant in runs:
        created = as_utc(created)
        if created < prev:
            continue
        b = per_day.get(created.date().isoformat())
        if b is not None:
            b[0] += st == "succeeded"
            b[1] += st == "failed"
        if created >= cur:
            cur_runs += 1
            cur_failed += st == "failed"
        else:
            prev_runs += 1
            prev_failed += st == "failed"

    cost_month = await _scalar(db, select(func.coalesce(func.sum(BuilderRun.cost_usd), 0.0)).where(BuilderRun.created_at >= month))
    cost_last = await _scalar(
        db, select(func.coalesce(func.sum(BuilderRun.cost_usd), 0.0)).where(BuilderRun.created_at >= last_month, BuilderRun.created_at < month)
    )

    # Signups by week (Monday-start), last 8 weeks.
    week0 = today - timedelta(days=today.weekday()) - timedelta(weeks=7)
    weeks = {(week0 + timedelta(weeks=i)).date().isoformat(): 0 for i in range(8)}
    for (created,) in (await db.execute(select(User.created_at).where(User.created_at >= week0))).all():
        c = as_utc(created)
        key = (_start_of_day(c) - timedelta(days=c.weekday())).date().isoformat()
        if key in weeks:
            weeks[key] += 1

    # Apps: people connected (their own rows) and tool calls in the window.
    servers = {s.id: s.name for s in (await db.execute(select(VendorMCPServer.id, VendorMCPServer.name))).all()}
    people = dict(
        (await db.execute(
            select(VendorMCPCredential.server_id, func.count()).where(VendorMCPCredential.user_id.is_not(None)).group_by(VendorMCPCredential.server_id)
        )).all()
    )
    calls = dict(
        (await db.execute(
            select(BuilderToolCall.server_id, func.count()).where(BuilderToolCall.created_at >= cur).group_by(BuilderToolCall.server_id)
        )).all()
    )
    top_apps = sorted(
        (TopApp(id=i, name=n, people=people.get(i, 0), tool_calls=calls.get(i, 0)) for i, n in servers.items() if people.get(i) or calls.get(i)),
        key=lambda a: (-a.tool_calls, -a.people, a.name),
    )[:6]

    # Accounts: runs and cost this month.
    by_tenant = (
        await db.execute(
            select(BuilderRun.tenant_id, func.count(), func.coalesce(func.sum(BuilderRun.cost_usd), 0.0))
            .where(BuilderRun.created_at >= month).group_by(BuilderRun.tenant_id)
        )
    ).all()
    tenants = {t.id: t for t in (await db.execute(select(Tenant).where(Tenant.id.in_([r[0] for r in by_tenant])))).scalars()}
    top_accounts = sorted(
        (
            TopAccount(id=tid, name=tenants[tid].name, is_personal=tenants[tid].is_personal, runs=n, cost_usd=round(float(c), 4))
            for tid, n, c in by_tenant if tid in tenants
        ),
        key=lambda a: (-a.runs, -a.cost_usd),
    )[:6]

    return Overview(
        days=days,
        people_total=int(await _scalar(db, select(func.count()).select_from(User))),
        active_people=Pair(current=await active(cur, None), previous=await active(prev, cur)),
        new_people=Pair(current=await joined(cur, None), previous=await joined(prev, cur)),
        runs=Pair(current=cur_runs, previous=prev_runs),
        failed_runs=Pair(current=cur_failed, previous=prev_failed),
        cost_month_usd=round(cost_month, 4),
        cost_last_month_usd=round(cost_last, 4),
        run_days=[RunDay(date=d, succeeded=v[0], failed=v[1]) for d, v in per_day.items()],
        signups_by_week=[WeekCount(week_start=k, count=v) for k, v in weeks.items()],
        top_apps=top_apps,
        top_accounts=top_accounts,
    )


@router.get("/platform/accounts/{tenant_id}", response_model=AccountDetail)
async def platform_account(tenant_id: str, _user: CurrentUser = _admin, db: AsyncSession = Depends(get_db)):
    from builder.models import BuilderRun
    from builder.runs.db import utcnow

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    members = (await db.execute(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at))).scalars().all()
    ids = [m.id for m in members]
    apps = (
        await db.execute(
            select(VendorMCPServer.id, VendorMCPServer.name, func.count())
            .join(VendorMCPCredential, VendorMCPCredential.server_id == VendorMCPServer.id)
            .where(VendorMCPCredential.user_id.in_(ids or [""]))
            .group_by(VendorMCPServer.id, VendorMCPServer.name)
            .order_by(VendorMCPServer.name)
        )
    ).all()
    month = _month_start(utcnow())
    runs, failed, cost = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(BuilderRun.status == "failed"),
                func.coalesce(func.sum(BuilderRun.cost_usd), 0.0),
            ).where(BuilderRun.tenant_id == tenant_id, BuilderRun.created_at >= month)
        )
    ).one()
    last_active = (
        await db.execute(
            select(func.max(AuditEvent.created_at)).where(AuditEvent.user_id.in_(ids or [""]), AuditEvent.action.in_(_PRESENCE))
        )
    ).scalar_one()
    return AccountDetail(
        id=tenant.id, name=tenant.name, is_personal=tenant.is_personal, status=tenant.status, created_at=tenant.created_at,
        members=[Member(id=m.id, name=m.full_name or "", email=m.email, role=m.role, is_active=m.is_active, joined=m.created_at) for m in members],
        apps=[AccountApp(id=i, name=n, people=c) for i, n, c in apps],
        runs_month=int(runs or 0), failed_month=int(failed or 0), cost_month_usd=round(float(cost or 0), 4), last_active=last_active,
    )
