"""add source_repo_url and env_vars to vendor_mcp_servers

Revision ID: 20260902080418_add_source_repo_url_env_vars_to_vendor_mcp_servers
Revises: f9a0b1c2d3e4
Create Date: 2026-09-02 08:04:18.000000

Adds ``vendor_mcp_servers.source_repo_url`` (GitHub origin) and ``vendor_mcp_servers.env_vars``
(detected environment variables) — consumed by the Universal MCP Engine.

GitHub-hosted MCP servers (baremetal/stdio) may retain a pointer to the repo URL for
context; ``env_vars`` stores the analysis result of required credentials.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260902080418"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column(
        "vendor_mcp_servers",
        sa.Column(
            "source_repo_url",
            sa.String(length=512),
            nullable=True,
        ),
    )
    op.add_column(
        "vendor_mcp_servers",
        sa.Column(
            "env_vars",
            sa.JSON(),
            nullable=True,
            server_default="{}",
        ),
    )

def downgrade() -> None:
    op.drop_column("vendor_mcp_servers", "env_vars")
    op.drop_column("vendor_mcp_servers", "source_repo_url")