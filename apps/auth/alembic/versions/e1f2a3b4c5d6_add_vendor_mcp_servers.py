"""add vendor_mcp_servers and tenant_resource_grants

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-09-01 00:00:00.000000

Replaces the ``vendor_tools`` and ``tool_embeddings`` tables with
``vendor_mcp_servers`` (Phase 1 MCP):

  * ``vendor_mcp_servers``  — registered MCP servers (SSE/Stdio).
  * ``tenant_resource_grants`` — maps a resource (mcp/datasource) to
    a tenant; all members inherit access.

SQLite-safe: ``bound_tools`` uses portable ``sa.JSON()``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "e1f2a3b4c5d6"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old tool tables and index if they exist (idempotent).
    op.execute("DROP INDEX IF EXISTS ix_tool_embeddings_tool_id")
    op.execute("DROP TABLE IF EXISTS tool_embeddings")
    op.execute("DROP INDEX IF EXISTS ix_vendor_tools_is_global")
    op.execute("DROP INDEX IF EXISTS ix_vendor_tools_category")
    op.execute("DROP INDEX IF EXISTS ix_vendor_tools_name")
    op.execute("DROP TABLE IF EXISTS vendor_tools")

    # Create new MCP server table.
    op.create_table(
        "vendor_mcp_servers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("transport", sa.String(length=32), nullable=False, server_default="sse"),
        sa.Column("server_url", sa.String(length=512), nullable=False),
        sa.Column("bound_tools", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vendor_mcp_servers_name", "vendor_mcp_servers", ["name"])
    op.create_index("ix_vendor_mcp_servers_is_global", "vendor_mcp_servers", ["is_global"])

    # Recreate tenant_resource_grants with consistent structure.
    op.execute("DROP TABLE IF EXISTS tenant_resource_grants")
    op.create_table(
        "tenant_resource_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_resource_grants_tenant_id", "tenant_resource_grants", ["tenant_id"])
    op.create_index("ix_tenant_resource_grants_resource_id", "tenant_resource_grants", ["resource_id"])
    op.create_index(
        "ix_grant_tenant_resource",
        "tenant_resource_grants",
        ["tenant_id", "resource_type", "resource_id"],
        unique=True,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_grant_tenant_resource")
    op.execute("DROP INDEX IF EXISTS ix_tenant_resource_grants_resource_id")
    op.execute("DROP INDEX IF EXISTS ix_tenant_resource_grants_tenant_id")
    op.execute("DROP TABLE IF EXISTS tenant_resource_grants")
    op.execute("DROP INDEX IF EXISTS ix_vendor_mcp_servers_is_global")
    op.execute("DROP INDEX IF EXISTS ix_vendor_mcp_servers_name")
    op.execute("DROP TABLE IF EXISTS vendor_mcp_servers")

    op.create_table(
        "vendor_tools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="POST"),
        sa.Column("endpoint_url", sa.String(length=512), nullable=True),
        sa.Column("parameters_schema", sa.JSON(), nullable=False),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("vault_secret_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vendor_tools_name", "vendor_tools", ["name"])
    op.create_index("ix_vendor_tools_category", "vendor_tools", ["category"])
    op.create_index("ix_vendor_tools_is_global", "vendor_tools", ["is_global"])

    op.create_table(
        "tool_embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=36), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("dim", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["vendor_tools.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_embeddings_tool_id", "tool_embeddings", ["tool_id"], unique=True)