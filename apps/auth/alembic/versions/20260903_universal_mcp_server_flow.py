"""Universal MCP Server Flow — add new columns and vendor_mcp_tools table.

Revision ID: 20260903_universal_mcp_server_flow
Revises: d8dca9072d28
Create Date: 2026-09-03 23:59:43.000000

Architecture doc §24 changes
=============================
vendor_mcp_servers
------------------
New columns added to support the universal MCP detection and launch pipeline:

  Status / ownership:
    status            STRING(32)    NOT NULL  DEFAULT 'UNCONNECTED'
    ownership_type    STRING(32)    NULL

  Source discovery:
    source_type       STRING(32)    NULL   -- 'github' | 'remote' | 'local'
    source_repo       STRING(512)   NULL   -- 'owner/repo'
    source_branch     STRING(255)   NULL   -- e.g. 'main'
    source_subpath    STRING(512)   NULL   -- e.g. 'src/filesystem'

  Transport detection:
    transport_confidence  FLOAT     NULL   -- 0.0–1.0
    transport_evidence    JSON      NULL   -- [{source, reason}]

  Runtime / launch:
    runtime_type      STRING(32)    NULL   -- node|python|go|rust|docker|binary|unknown
    command           STRING(1024)  NULL
    args              JSON          NULL
    working_directory STRING(1024)  NULL

  Network endpoint:
    endpoint          STRING(512)   NULL

  Auth (normalized):
    auth_type         STRING(64)    NULL
    auth_schema       JSON          NULL

Backward-compat columns (server_url, source_repo_url, auth_config, env_vars,
bound_tools) are left untouched.

vendor_mcp_tools  (new table)
-----------------------------
    id              STRING(36)   PK
    mcp_server_id   STRING(36)   FK → vendor_mcp_servers.id CASCADE
    name            STRING(255)  NOT NULL
    description     TEXT         NOT NULL  DEFAULT ''
    input_schema    JSON         NULL
    output_schema   JSON         NULL
    created_at      DATETIME     NOT NULL
    updated_at      DATETIME     NOT NULL
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------
revision = "20260903_universal_mcp_server_flow"
down_revision = "d8dca9072d28"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Helpers — new columns on vendor_mcp_servers
# ---------------------------------------------------------------------------
_NEW_SERVER_COLUMNS: list[sa.Column] = [
    # Status / ownership
    sa.Column("status", sa.String(32), nullable=False, server_default="UNCONNECTED"),
    sa.Column("ownership_type", sa.String(32), nullable=True),
    # Source
    sa.Column("source_type", sa.String(32), nullable=True),
    sa.Column("source_repo", sa.String(512), nullable=True),
    sa.Column("source_branch", sa.String(255), nullable=True),
    sa.Column("source_subpath", sa.String(512), nullable=True),
    # Transport detection
    sa.Column("transport_confidence", sa.Float(), nullable=True),
    sa.Column("transport_evidence", sa.JSON(), nullable=True),
    # Runtime / launch
    sa.Column("runtime_type", sa.String(32), nullable=True),
    sa.Column("command", sa.String(1024), nullable=True),
    sa.Column("args", sa.JSON(), nullable=True),
    sa.Column("working_directory", sa.String(1024), nullable=True),
    # Network endpoint
    sa.Column("endpoint", sa.String(512), nullable=True),
    # Auth (normalized)
    sa.Column("auth_type", sa.String(64), nullable=True),
    sa.Column("auth_schema", sa.JSON(), nullable=True),
]

# Column names we need to remove on downgrade (in reverse order for clarity)
_NEW_SERVER_COLUMN_NAMES: list[str] = [c.name for c in _NEW_SERVER_COLUMNS]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add new columns to vendor_mcp_servers
    # ------------------------------------------------------------------
    with op.batch_alter_table("vendor_mcp_servers", schema=None) as batch_op:
        for column in _NEW_SERVER_COLUMNS:
            batch_op.add_column(column)

        # Index on status for fast UNCONNECTED/VERIFIED filtering
        batch_op.create_index(
            "ix_vendor_mcp_servers_status",
            ["status"],
            unique=False,
        )
        # Index on source_type for filtering by discovery path
        batch_op.create_index(
            "ix_vendor_mcp_servers_source_type",
            ["source_type"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # 2. Create vendor_mcp_tools table
    # ------------------------------------------------------------------
    op.create_table(
        "vendor_mcp_tools",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "mcp_server_id",
            sa.String(36),
            sa.ForeignKey("vendor_mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )

    # Index on mcp_server_id for fast per-server tool lookups
    op.create_index(
        "ix_vendor_mcp_tools_mcp_server_id",
        "vendor_mcp_tools",
        ["mcp_server_id"],
        unique=False,
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 2. Drop vendor_mcp_tools table
    # ------------------------------------------------------------------
    op.drop_index("ix_vendor_mcp_tools_mcp_server_id", table_name="vendor_mcp_tools")
    op.drop_table("vendor_mcp_tools")

    # ------------------------------------------------------------------
    # 1. Remove new columns from vendor_mcp_servers
    # ------------------------------------------------------------------
    with op.batch_alter_table("vendor_mcp_servers", schema=None) as batch_op:
        # Drop indexes first
        batch_op.drop_index("ix_vendor_mcp_servers_status")
        batch_op.drop_index("ix_vendor_mcp_servers_source_type")

        # Drop columns in reverse order of addition
        for col_name in reversed(_NEW_SERVER_COLUMN_NAMES):
            batch_op.drop_column(col_name)
