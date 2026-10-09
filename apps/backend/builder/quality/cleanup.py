"""Removing an agent's/workflow's tests with it (SQLite doesn't cascade)."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from builder.models import BuilderTestCase, BuilderTestResult, BuilderTestRun


async def delete_tests(db: AsyncSession, cases_where, runs_where) -> None:
    """Delete test cases and test runs (with their results) matching these conditions.
    The runs a test started stay, like all run history."""
    run_ids = select(BuilderTestRun.id).where(runs_where)
    await db.execute(delete(BuilderTestResult).where(BuilderTestResult.test_run_id.in_(run_ids)))
    await db.execute(delete(BuilderTestRun).where(runs_where))
    await db.execute(delete(BuilderTestCase).where(cases_where))


__all__ = ["delete_tests"]
