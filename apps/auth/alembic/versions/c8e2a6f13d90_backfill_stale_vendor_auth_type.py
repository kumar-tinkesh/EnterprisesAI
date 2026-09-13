"""backfill stale vendor_mcp_servers.auth_type from auth_config

Revision ID: c8e2a6f13d90
Revises: b4c1f0d9a2e7
Create Date: 2026-09-13 00:00:00.000000

The legacy ``/mcp/legacy`` registration endpoint (``create_mcp_server`` in
``vendor/services/mcp_service/registration.py``) never set the top-level
``auth_type`` column on newly-created rows — only the richer, correctly
detected value inside ``auth_config["auth_type"]`` was set. That endpoint
code path is already fixed (it now sets both consistently), but any row
created *before* that fix is stuck with a stale top-level ``auth_type``
(observed in the wild: ``"none"`` where ``auth_config`` says
``"device_pairing"``, ``"env"`` where it says ``"oauth2"``/``"bearer"``,
etc). Every reader of the *top-level* column — the catalog API, the
device-pairing bridge gate — disagrees with readers of ``auth_config``
(``resolve_auth``, the bridge gate) for exactly these rows, which is
confusing at best (wrong credential UI shown) and a real functional bug at
worst (the WhatsApp bridge gate keys off ``auth_config``, so a stale
top-level value made the UI and the enforced behavior visibly disagree).

One-time backfill: for every row where the two disagree, adopt
``auth_config``'s value as authoritative (it was always the more complete
source of truth). No schema change.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "c8e2a6f13d90"
down_revision = "b4c1f0d9a2e7"
branch_labels = None
depends_on = None

_servers = sa.table(
    "vendor_mcp_servers",
    sa.column("id", sa.String),
    sa.column("auth_type", sa.String),
    sa.column("auth_config", sa.JSON),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(_servers.c.id, _servers.c.auth_type, _servers.c.auth_config)).fetchall()
    for row_id, auth_type, auth_config_raw in rows:
        auth_config = (
            auth_config_raw
            if isinstance(auth_config_raw, dict)
            else json.loads(auth_config_raw or "{}")
        )
        effective = auth_config.get("auth_type")
        if effective and effective != auth_type:
            bind.execute(
                _servers.update().where(_servers.c.id == row_id).values(auth_type=effective)
            )


def downgrade() -> None:
    # Not reversible — the original stale values aren't worth restoring.
    pass
