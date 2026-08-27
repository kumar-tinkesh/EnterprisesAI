"""Programmatic Alembic migrations.

The FastAPI app (and the Docker entrypoint) both funnel through here so that
*any* environment — a fresh ``git pull``, local dev, or a container — ends up
with the schema at ``head`` automatically, on whatever ``DATABASE_URL`` points
at (SQLite locally, PostgreSQL in prod). Changing the database is just an env
var change; the same migration chain builds it natively.
"""
from __future__ import annotations

from pathlib import Path

from src.config import get_settings


def _package_root() -> Path:
    """``apps/auth`` — this file lives at apps/auth/src/db/migrations.py."""
    return Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    """Apply pending Alembic migrations up to ``head`` (synchronous call).

    Builds the Alembic :class:`~alembic.config.Config` in memory so no
    ``alembic.ini`` lookup is needed; the URL always comes from the global
    settings so ``.env`` / OS env stay the single source of truth.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_package_root() / "alembic"))
    # env.py re-reads settings, but set it explicitly too so any use of
    # config.get_main_option("sqlalchemy.url") inside env.py is correct.
    cfg.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)
    command.upgrade(cfg, "head")