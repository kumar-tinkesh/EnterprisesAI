"""Schedules: keep them in step with their workflows, and start the runs that are due.

* ``sync_workflow_schedules`` — called on every workflow save: one row per
  Schedule trigger step, created/updated/removed to match the graph.
* ``fire_due`` — called by every worker's schedule loop. Each due occurrence is
  *claimed* with a conditional update on ``next_run_at`` (only one worker's
  update matches), so it starts exactly one run however many workers poll.
  A worker that was down for a while fires a missed schedule once, then
  carries on from now — no burst of catch-up runs.
* ``start_scheduled_run`` — runs as the schedule's owner after the same checks
  a person's Run button goes through; if they fail, the occurrence is skipped
  with the reason recorded (and a schedule whose owner lost access is paused).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.models import User

from builder.models import BuilderAgent, BuilderSchedule, BuilderWorkflow
from builder.runs.db import as_utc, session_factory, utcnow
from builder.runs.service import create_agent_run, create_workflow_run
from builder.runs.start import agent_run_problems, workflow_run_problems
from builder.schedules.cron import ScheduleError, next_run, validate

logger = logging.getLogger("builder.schedules")

STARTED, SKIPPED, ERROR = "started", "skipped", "error"


def apply_timing(row: BuilderSchedule, *, cron: str, tz: str, enabled: bool, now: datetime | None = None) -> None:
    """Set cron/timezone/enabled and recompute ``next_run_at`` when they changed
    (or it has none). An unusable cron leaves the schedule switched off."""
    cron, tz = cron.strip(), tz or "UTC"
    changed = (row.cron, row.timezone, row.enabled) != (cron, tz, enabled) or (enabled and row.next_run_at is None)
    row.cron, row.timezone, row.enabled = cron, tz, enabled
    if not changed:
        return
    if not enabled or not cron:
        row.enabled, row.next_run_at = bool(enabled and cron), None
        return
    try:
        validate(cron, tz)
        row.next_run_at = next_run(cron, tz, now or utcnow())
    except ScheduleError:
        row.enabled, row.next_run_at = False, None


async def sync_workflow_schedules(db: AsyncSession, workflow: BuilderWorkflow) -> None:
    """Mirror the workflow's Schedule trigger step(s) into builder_schedules.
    Runs inside the caller's transaction (the caller commits)."""
    wanted = {n["id"]: n for n in workflow.nodes or [] if n.get("type") == "schedule_trigger" and n.get("id")}
    rows = (await db.execute(select(BuilderSchedule).where(BuilderSchedule.workflow_id == workflow.id))).scalars().all()
    existing = {r.node_id: r for r in rows}
    for row in rows:
        if row.node_id not in wanted:
            await db.delete(row)
    for node_id, node in wanted.items():
        cfg = node.get("schedule") or {}
        row = existing.get(node_id)
        if row is None:
            row = BuilderSchedule(
                tenant_id=workflow.tenant_id, owner_id=workflow.owner_id, kind="workflow",
                workflow_id=workflow.id, node_id=node_id, cron="", timezone="UTC", enabled=False, input={},
            )
            db.add(row)
        row.input = {"text": str(cfg.get("input") or ""), "variables": dict(cfg.get("variables") or {})}
        apply_timing(
            row, cron=str(cfg.get("cron") or ""), tz=str(cfg.get("timezone") or "UTC"),
            enabled=cfg.get("enabled", True) is not False,
        )


# ── firing ──────────────────────────────────────────────────────────────────


async def _owner(db: AsyncSession, owner_id: str) -> CurrentUser | None:
    user = await db.get(User, owner_id)
    if user is None or not user.is_active or not user.tenant_id:
        return None
    return CurrentUser(id=user.id, email=user.email, full_name=user.full_name, role=user.role, tenant_id=user.tenant_id)


async def start_scheduled_run(db: AsyncSession, schedule: BuilderSchedule) -> tuple[str, str | None, str | None]:
    """Start one run for ``schedule`` as its owner -> (status, run_id, error)."""
    user = await _owner(db, schedule.owner_id)
    if user is None or user.tenant_id != schedule.tenant_id:
        schedule.enabled, schedule.next_run_at = False, None
        return ERROR, None, "Paused: the person who set this schedule no longer has access."
    text = str((schedule.input or {}).get("text") or "")
    variables = dict((schedule.input or {}).get("variables") or {})

    if schedule.kind == "agent":
        agent = await db.get(BuilderAgent, schedule.agent_id) if schedule.agent_id else None
        if agent is None or agent.tenant_id != schedule.tenant_id:
            schedule.enabled, schedule.next_run_at = False, None
            return ERROR, None, "Paused: the agent no longer exists."
        if not text.strip():
            return SKIPPED, None, "Skipped: add what this schedule should ask the agent."
        problems = await agent_run_problems(db, user, agent)
        if problems:
            return SKIPPED, None, "Skipped: " + " ".join(p.message for p in problems)
        run = await create_agent_run(db, user, agent, text=text, variables=variables, schedule_id=schedule.id)
        return STARTED, run.id, None

    workflow = await db.get(BuilderWorkflow, schedule.workflow_id) if schedule.workflow_id else None
    if workflow is None or workflow.tenant_id != schedule.tenant_id:
        schedule.enabled, schedule.next_run_at = False, None
        return ERROR, None, "Paused: the workflow no longer exists."
    problems = await workflow_run_problems(db, user, workflow, variables)
    if problems:
        return SKIPPED, None, "Skipped: " + " ".join(p.message for p in problems)
    run = await create_workflow_run(db, user, workflow, text=text, variables=variables, schedule_id=schedule.id)
    return STARTED, run.id, None


async def _fire_one(schedule_id: str, due_at: datetime, now: datetime) -> bool:
    async with session_factory() as db:
        schedule = await db.get(BuilderSchedule, schedule_id)
        if schedule is None or not schedule.enabled:
            return False
        try:
            following = next_run(schedule.cron, schedule.timezone, max(now, as_utc(due_at)))
        except Exception:  # noqa: BLE001 — cron/zone no longer usable: fire this once, then stop
            following = None
        claimed = await db.execute(
            update(BuilderSchedule)
            .where(BuilderSchedule.id == schedule_id, BuilderSchedule.next_run_at == due_at, BuilderSchedule.enabled.is_(True))
            .values(next_run_at=following, enabled=following is not None, last_run_at=now)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        if claimed.rowcount != 1:
            return False  # another worker took this occurrence
        await db.refresh(schedule)
        try:
            status, run_id, error = await start_scheduled_run(db, schedule)
        except Exception as exc:  # noqa: BLE001 — one bad schedule must not stop the loop
            logger.exception("schedule %s failed to start a run", schedule_id)
            await db.rollback()
            schedule = await db.get(BuilderSchedule, schedule_id)
            status, run_id, error = ERROR, None, f"Couldn't start the run: {exc}"
        if schedule is not None:
            schedule.last_status, schedule.last_run_id, schedule.last_error = status, run_id, error
            await db.commit()
        logger.info("schedule %s fired: %s %s", schedule_id, status, run_id or error or "")
        return status == STARTED


async def fire_due(*, now: datetime | None = None, limit: int = 25) -> int:
    """Start every schedule that is due; returns how many runs started."""
    now = now or utcnow()
    async with session_factory() as db:
        due = (
            await db.execute(
                select(BuilderSchedule.id, BuilderSchedule.next_run_at)
                .where(BuilderSchedule.enabled.is_(True), BuilderSchedule.next_run_at.is_not(None), BuilderSchedule.next_run_at <= now)
                .order_by(BuilderSchedule.next_run_at)
                .limit(limit)
            )
        ).all()
    started = 0
    for schedule_id, due_at in due:
        if await _fire_one(schedule_id, due_at, now):
            started += 1
    return started


__all__ = ["apply_timing", "sync_workflow_schedules", "start_scheduled_run", "fire_due"]
