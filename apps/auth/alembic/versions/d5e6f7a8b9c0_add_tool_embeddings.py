"""add tool_embeddings

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-31 01:00:00.000000

Adds the ``tool_embeddings`` table — one embedding vector per vendor tool,
stored as portable ``sa.JSON()`` (list[float]) for semantic catalog matching.
SQLite-safe (no ``JSONB`` / pgvector); the schema is swappable to a native
vector index (e.g. sqlite-vec) later without changing the model API.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.create_index(
        "ix_tool_embeddings_tool_id",
        "tool_embeddings",
        ["tool_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_embeddings_tool_id", table_name="tool_embeddings")
    op.drop_table("tool_embeddings")