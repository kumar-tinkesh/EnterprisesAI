"""add vendor_mcp_credentials table

Revision ID: a7b8c9d0e1f2
Revises: f9a0b1c2d3e4
Create Date: 2026-09-02 00:00:00.000000

Adds ``vendor_mcp_credentials`` — Fernet-encrypted per-server (optionally
per-tenant) credential storage used by ``vendor_resources.services.mcp_auth``
to natively resolve MCP server auth (OAuth2 client secrets/refresh tokens,
API keys, basic passwords). SQLite-safe.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_mcp_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "server_id",
            sa.String(length=36),
            sa.ForeignKey("vendor_mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("encrypted_credentials", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vendor_mcp_credentials_server_id",
        "vendor_mcp_credentials",
        ["server_id"],
    )
    op.create_index(
        "ix_vendor_mcp_credentials_tenant_id",
        "vendor_mcp_credentials",
        ["tenant_id"],
    )
    op.create_index(
        "ix_vmc_server_tenant",
        "vendor_mcp_credentials",
        ["server_id", "tenant_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_vmc_server_tenant", table_name="vendor_mcp_credentials")
    op.drop_index("ix_vendor_mcp_credentials_tenant_id", table_name="vendor_mcp_credentials")
    op.drop_index("ix_vendor_mcp_credentials_server_id", table_name="vendor_mcp_credentials")
    op.drop_table("vendor_mcp_credentials")