"""add embedding columns to vendor_mcp_servers and vendor_mcp_tools

Revision ID: 741056495a49
Revises: 20260903_universal_mcp_server_flow
Create Date: 2026-09-06 00:31:43.182942

Adds semantic-search columns to both tables, mirroring the same shape:

    embedding        JSON      NULL   -- list[float], from llm_gateway.embed()
    embedding_model   STRING(128) NULL -- e.g. "gemini-embedding-001"
    dim               INTEGER    NULL  -- len(embedding); lets callers detect
                                        -- a stale/mismatched vector instead
                                        -- of comparing garbage after an
                                        -- embedding-provider switch.

``vendor_mcp_servers.embedding`` is computed from "name. description" (server
selection); ``vendor_mcp_tools.embedding`` from "name. description" plus the
tool's input_schema property names (tool selection within a server). See
vendor_resources.services.catalog_engine.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "741056495a49"
down_revision = "20260903_universal_mcp_server_flow"
branch_labels = None
depends_on = None

_EMBEDDING_COLUMNS: list[sa.Column] = [
    sa.Column("embedding", sa.JSON(), nullable=True),
    sa.Column("embedding_model", sa.String(128), nullable=True),
    sa.Column("dim", sa.Integer(), nullable=True),
]
_EMBEDDING_COLUMN_NAMES: list[str] = [c.name for c in _EMBEDDING_COLUMNS]


def upgrade() -> None:
    with op.batch_alter_table("vendor_mcp_servers", schema=None) as batch_op:
        for column in _EMBEDDING_COLUMNS:
            batch_op.add_column(column.copy())

    with op.batch_alter_table("vendor_mcp_tools", schema=None) as batch_op:
        for column in _EMBEDDING_COLUMNS:
            batch_op.add_column(column.copy())


def downgrade() -> None:
    with op.batch_alter_table("vendor_mcp_tools", schema=None) as batch_op:
        for col_name in reversed(_EMBEDDING_COLUMN_NAMES):
            batch_op.drop_column(col_name)

    with op.batch_alter_table("vendor_mcp_servers", schema=None) as batch_op:
        for col_name in reversed(_EMBEDDING_COLUMN_NAMES):
            batch_op.drop_column(col_name)
