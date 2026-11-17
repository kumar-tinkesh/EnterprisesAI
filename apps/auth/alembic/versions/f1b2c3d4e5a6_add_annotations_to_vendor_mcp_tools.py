"""add annotations to vendor_mcp_tools

Revision ID: f1b2c3d4e5a6
Revises: e7a1c9d4b2f0
Create Date: 2026-10-07 18:00:00.000000

Stores each tool's MCP behaviour hints (read_only_hint, destructive_hint, …)
from tools/list, so the builder tool runtime can tell read tools from ones
that change data. Existing rows stay NULL until the server is re-verified;
the runtime then falls back to classifying by the tool's name.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1b2c3d4e5a6"
down_revision = "e7a1c9d4b2f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vendor_mcp_tools") as batch:
        batch.add_column(sa.Column("annotations", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vendor_mcp_tools") as batch:
        batch.drop_column("annotations")
