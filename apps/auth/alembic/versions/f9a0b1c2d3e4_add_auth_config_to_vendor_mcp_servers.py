"""add auth_config to vendor_mcp_servers

Revision ID: f9a0b1c2d3e4
Revises: e1f2a3b4c5d6
Create Date: 2026-09-02 00:00:00.000000

Adds ``vendor_mcp_servers.auth_config`` — the natively detected credential
requirement for the server (auth_type + credential_fields + hints), produced
by ``vendor_resources.services.mcp_detect`` when a vendor admin registers or
probes an MCP URL. SQLite-safe: portable ``sa.JSON()``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f9a0b1c2d3e4"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_mcp_servers",
        sa.Column("auth_config", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("vendor_mcp_servers", "auth_config")
