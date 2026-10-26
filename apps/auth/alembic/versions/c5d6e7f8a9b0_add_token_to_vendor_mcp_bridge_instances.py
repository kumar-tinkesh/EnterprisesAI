"""add token_encrypted to vendor_mcp_bridge_instances

Revision ID: c5d6e7f8a9b0
Revises: b9e4d2c71f05
Create Date: 2026-10-16 00:00:00.000000

Each user's WhatsApp bridge now runs in its own container (started by the
whatsapp-orchestrator service) whose REST API requires a per-instance token.
The token outlives any one backend/worker process — both build that user's
MCP server config from it — so it's stored here, Fernet-encrypted like
``vendor_mcp_credentials``. ``data_dir``/``port`` now hold the container's
session volume name and fixed API port.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b9e4d2c71f05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vendor_mcp_bridge_instances") as batch:
        batch.add_column(sa.Column("token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vendor_mcp_bridge_instances") as batch:
        batch.drop_column("token_encrypted")
