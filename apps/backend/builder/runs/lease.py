"""Which worker holds a run — decided by one conditional UPDATE in the database.

    claim      queued -> running, or take over a running run whose lease lapsed
    heartbeat  extend my lease; returns False if I no longer hold it
    release    leave running (to waiting / a final state) only if I still hold it

Every write is ``WHERE lease_owner = me``-guarded, so a worker that lost its
lease (paused process, network split) can't overwrite the new holder's work.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, case, or_, select, update

from builder.config import get_builder_settings
from builder.models import BuilderApproval, BuilderRun
from builder.runs import states
from builder.runs.db import session_factory, utcnow


async def claim(run_id: str, worker_id: str) -> bool:
    settings = get_builder_settings()
    now = utcnow()
    async with session_factory() as db:
        result = await db.execute(
            update(BuilderRun)
            .where(
                BuilderRun.id == run_id,
                or_(
                    BuilderRun.status == states.QUEUED,
                    and_(BuilderRun.status == states.RUNNING, BuilderRun.lease_expires_at < now),
                ),
            )
            .values(
                status=states.RUNNING,
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=settings.RUN_LEASE_SECONDS),
                heartbeat_at=now,
                # Counts recoveries only: taking over a lapsed lease means the
                # previous worker died. Resuming after an approval doesn't count.
                attempts=case((BuilderRun.status == states.RUNNING, BuilderRun.attempts + 1), else_=BuilderRun.attempts),
            )
        )
        await db.commit()
        if result.rowcount != 1:
            return False
        run = await db.get(BuilderRun, run_id)
        if run.started_at is None:
            run.started_at = now
            await db.commit()
        return True


async def heartbeat(run_id: str, worker_id: str) -> bool:
    settings = get_builder_settings()
    now = utcnow()
    async with session_factory() as db:
        result = await db.execute(
            update(BuilderRun)
            .where(BuilderRun.id == run_id, BuilderRun.lease_owner == worker_id, BuilderRun.status == states.RUNNING)
            .values(lease_expires_at=now + timedelta(seconds=settings.RUN_LEASE_SECONDS), heartbeat_at=now)
        )
        await db.commit()
        return result.rowcount == 1


async def release(run_id: str, worker_id: str, *, status: str, **values) -> bool:
    """Move a run I hold to ``status`` (waiting / succeeded / failed / queued)."""
    now = utcnow()
    if status in states.TERMINAL:
        values.setdefault("finished_at", now)
    async with session_factory() as db:
        result = await db.execute(
            update(BuilderRun)
            .where(BuilderRun.id == run_id, BuilderRun.lease_owner == worker_id, BuilderRun.status == states.RUNNING)
            .values(status=status, lease_owner=None, lease_expires_at=None, **values)
        )
        await db.commit()
        return result.rowcount == 1


async def stuck_run_ids(limit: int = 100) -> list[str]:
    """Runs to re-enqueue: lease lapsed (worker died), queued too long (message
    lost), or waiting with nothing left to wait for (a decision raced the pause)."""
    settings = get_builder_settings()
    now = utcnow()
    pending_approval = (
        select(BuilderApproval.id)
        .where(BuilderApproval.run_id == BuilderRun.id, BuilderApproval.status == states.APPROVAL_PENDING)
        .exists()
    )
    async with session_factory() as db:
        decided = await db.execute(
            update(BuilderRun)
            .where(BuilderRun.status == states.WAITING, ~pending_approval)
            .values(status=states.QUEUED)
            .returning(BuilderRun.id)
        )
        requeued = list(decided.scalars())
        await db.commit()
        rows = await db.execute(
            select(BuilderRun.id)
            .where(
                or_(
                    and_(BuilderRun.status == states.RUNNING, BuilderRun.lease_expires_at < now),
                    and_(
                        BuilderRun.status == states.QUEUED,
                        BuilderRun.updated_at < now - timedelta(seconds=settings.RUN_REQUEUE_AFTER_SECONDS),
                    ),
                )
            )
            .limit(limit)
        )
        return list(dict.fromkeys(requeued + list(rows.scalars())))


__all__ = ["claim", "heartbeat", "release", "stuck_run_ids"]
