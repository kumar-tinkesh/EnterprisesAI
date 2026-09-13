"""add vendor_mcp_bridge_instances for native per-user device-pairing bridges

Revision ID: b4c1f0d9a2e7
Revises: 9f3a7c2b5e14
Create Date: 2026-09-13 00:00:00.000000

Adds ``vendor_mcp_bridge_instances`` to track one long-running,
QR-authenticated background bridge process per (server, user) pair — used
for ``device_pairing``-auth servers (e.g. WhatsApp) where there is no
static secret to store, only a process's live authenticated session.
Deliberately separate from ``vendor_mcp_credentials``: there is nothing to
encrypt here, just process identity (``data_dir``, ``port``) and status.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "b4c1f0d9a2e7"
down_revision = "9f3a7c2b5e14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_mcp_bridge_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data_dir", sa.String(length=512), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_connected_at", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["vendor_mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vendor_mcp_bridge_instances_server_id",
        "vendor_mcp_bridge_instances",
        ["server_id"],
    )
    op.create_index(
        "ix_vendor_mcp_bridge_instances_tenant_id",
        "vendor_mcp_bridge_instances",
        ["tenant_id"],
    )
    op.create_index(
        "ix_vendor_mcp_bridge_instances_user_id",
        "vendor_mcp_bridge_instances",
        ["user_id"],
    )
    op.create_index(
        "ix_bridge_server_user",
        "vendor_mcp_bridge_instances",
        ["server_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_bridge_server_user", table_name="vendor_mcp_bridge_instances")
    op.drop_index("ix_vendor_mcp_bridge_instances_user_id", table_name="vendor_mcp_bridge_instances")
    op.drop_index("ix_vendor_mcp_bridge_instances_tenant_id", table_name="vendor_mcp_bridge_instances")
    op.drop_index("ix_vendor_mcp_bridge_instances_server_id", table_name="vendor_mcp_bridge_instances")
    op.drop_table("vendor_mcp_bridge_instances")
