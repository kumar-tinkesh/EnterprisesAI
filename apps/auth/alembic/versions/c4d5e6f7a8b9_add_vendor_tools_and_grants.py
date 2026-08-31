"""add vendor_tools and tenant_resource_grants

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-31 00:00:00.000000

Introduces the Vendor Resources subsystem tables (Phase 1):

  * ``vendor_tools``           — declarative REST/OpenAPI tool definitions.
  * ``tenant_resource_grants`` — maps a resource (tool/mcp/datasource) to a
    tenant; all tenant members inherit access. The ``resource_type`` string
    accommodates ``mcp_server`` / ``data_source`` added in later phases without
    a further schema change.

SQLite-safe: ``parameters_schema`` uses portable ``sa.JSON()`` (SQLite has no
``JSONB``) and booleans use ``server_default=sa.text('0')``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.drop_index("ix_grant_tenant_resource", table_name="tenant_resource_grants")
    op.drop_index("ix_tenant_resource_grants_resource_id", table_name="tenant_resource_grants")
    op.drop_index("ix_tenant_resource_grants_tenant_id", table_name="tenant_resource_grants")
    op.drop_table("tenant_resource_grants")
    op.drop_index("ix_vendor_tools_is_global", table_name="vendor_tools")
    op.drop_index("ix_vendor_tools_category", table_name="vendor_tools")
    op.drop_index("ix_vendor_tools_name", table_name="vendor_tools")
    op.drop_table("vendor_tools")