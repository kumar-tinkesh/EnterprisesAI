#!/usr/bin/env python
"""Truncate all rows from every auth table in the LOCAL development database.

Usage (from repo root):
    cd apps/auth && uv run python tests/clean_tables.py

Or with explicit DB path:
    DATABASE_URL=sqlite+aiosqlite:///./auth.db uv run python tests/clean_tables.py

This does NOT drop the tables or touch the schema — it only deletes all rows.
If tables are missing, it creates them first via SQLAlchemy metadata.
Safe to re-run; idempotent.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Default to the local dev SQLite database if not overridden.
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/auth.db"

# Ensure the src package is importable when run from apps/auth/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import inspect, text  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import engine  # noqa: E402
from src.models import *  # noqa: E402,F401,F403  — register all tables


# Ordered from leaves → roots to respect FK constraints.
TABLE_ORDER = [
    "audit_events",
    "refresh_tokens",
    "workspace_members",
    "workspaces",
    "users",
    "tenants",
    "vendor_users",
]


async def clean() -> None:
    async with engine.begin() as conn:
        # Ensure all tables exist (creates any missing ones).
        await conn.run_sync(Base.metadata.create_all)

        # Discover which tables actually exist in the database.
        def _get_table_names(sync_conn):
            return inspect(sync_conn).get_table_names()

        existing_tables = set(await conn.run_sync(_get_table_names))

        print("🧹 Cleaning auth database tables...\n")

        for table_name in TABLE_ORDER:
            if table_name not in existing_tables:
                print(f"  ⏭  {table_name:<22} (not found, skipping)")
                continue
            result = await conn.execute(text(f"DELETE FROM {table_name}"))
            count = result.rowcount
            print(f"  ✅ {table_name:<22} — {count} row(s) deleted")

        print("\n✨ All tables cleaned successfully!")


if __name__ == "__main__":
    asyncio.run(clean())
