"""add user_id to vendor_mcp_credentials for per-user isolation

Revision ID: 9f3a7c2b5e14
Revises: 741056495a49
Create Date: 2026-09-07 00:00:00.000000

Adds ``user_id`` to ``vendor_mcp_credentials`` so each end user can store
their own credential for a server, isolated from every other user — even
another user in the same tenant. Replaces the single
``(server_id, tenant_id)`` unique index with two partial unique indexes so
the two row "kinds" don't collide:

  - a shared row per ``(server_id, tenant_id)`` where ``user_id IS NULL``
    (unchanged legacy behaviour — the vendor's own test/verification
    credential, and any pre-existing tenant-level fallback rows)
  - a per-user row per ``(server_id, user_id)`` where ``user_id IS NOT NULL``
    (new — one row per real end user, regardless of tenant)

Both Postgres and SQLite support partial (WHERE-qualified) unique indexes.
No backfill needed: every existing row has ``user_id IS NULL`` and keeps
its current uniqueness scope exactly.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9f3a7c2b5e14"
down_revision = "741056495a49"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vendor_mcp_credentials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            "ix_vendor_mcp_credentials_user_id", ["user_id"], unique=False
        )

    op.drop_index("ix_vmc_server_tenant", table_name="vendor_mcp_credentials")
    op.create_index(
        "ix_vmc_server_tenant_shared",
        "vendor_mcp_credentials",
        ["server_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
        sqlite_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ix_vmc_server_user",
        "vendor_mcp_credentials",
        ["server_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
        sqlite_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_vmc_server_user", table_name="vendor_mcp_credentials")
    op.drop_index("ix_vmc_server_tenant_shared", table_name="vendor_mcp_credentials")
    op.create_index(
        "ix_vmc_server_tenant",
        "vendor_mcp_credentials",
        ["server_id", "tenant_id"],
        unique=True,
    )

    with op.batch_alter_table("vendor_mcp_credentials", schema=None) as batch_op:
        batch_op.drop_index("ix_vendor_mcp_credentials_user_id")
        batch_op.drop_column("user_id")
