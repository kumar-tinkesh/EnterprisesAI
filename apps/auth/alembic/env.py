"""Alembic environment (async-ready, reads URL from global settings)."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.config import get_settings
from src.db.base import Base
from src.models import *  # noqa: F401,F403  (register all tables)

import sys
from pathlib import Path

# Register the Vendor domain tables (apps/backend) on the same Base.metadata
# so autogenerate sees them. IMPORTANT: import them under the SAME short module
# name the apps use (``vendor.models``, resolved via apps/backend on
# sys.path). Importing them as ``apps.backend.vendor.models`` would
# load the file a *second* time under a different module name and re-define the
# tables on the shared metadata → "Table 'vendor_mcp_servers' is already
# defined for this MetaData instance".
_ROOT = Path(__file__).resolve().parents[3]  # EnterpriseAI/ (this file: apps/auth/alembic/env.py)
for _p in (str(_ROOT), str(_ROOT / "apps" / "auth"), str(_ROOT / "apps" / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - import-time registration
    import vendor.models  # noqa: F401
except ImportError:
    pass

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject DATABASE_URL from pydantic-settings (global .env).
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())