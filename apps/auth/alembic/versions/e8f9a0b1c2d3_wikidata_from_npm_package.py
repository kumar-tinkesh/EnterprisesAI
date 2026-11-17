"""Wikidata MCP servers run from the npm package, with no credential fields

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-18 00:00:00.000000

cyanheads/wikidata-mcp-server was registered as a repo clone run with
``node dist/index.js``, but ``dist/`` is built with bun and isn't in the
repo, so it could never start ("Cannot find module …/dist/index.js"); and
repo analysis listed its HTTP-mode / telemetry variables (MCP_AUTH_SECRET_KEY,
MCP_PUBLIC_URL, OTEL_*) as required credentials. Rows registered from now on
get the package at analysis (vendor.services.known_servers); this fixes the
ones already there. No schema change.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None

REPO = "cyanheads/wikidata-mcp-server"

_servers = sa.table(
    "vendor_mcp_servers",
    sa.column("id", sa.String),
    sa.column("source_repo_url", sa.String),
    sa.column("source_repo", sa.String),
    sa.column("server_url", sa.String),
    sa.column("command", sa.String),
    sa.column("args", sa.JSON),
    sa.column("runtime_type", sa.String),
    sa.column("working_directory", sa.String),
    sa.column("env_vars", sa.JSON),
    sa.column("transport", sa.String),
    sa.column("auth_type", sa.String),
    sa.column("auth_schema", sa.JSON),
    sa.column("auth_config", sa.JSON),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_servers.c.id, _servers.c.source_repo_url, _servers.c.source_repo, _servers.c.server_url, _servers.c.auth_config)
    ).fetchall()
    for row_id, repo_url, repo, server_url, auth_config_raw in rows:
        if not any(REPO in (p or "").lower() for p in (repo_url, repo, server_url)):
            continue
        base = auth_config_raw if isinstance(auth_config_raw, dict) else json.loads(auth_config_raw or "{}")
        bind.execute(
            _servers.update().where(_servers.c.id == row_id).values(
                command="npx", args=["-y", "@cyanheads/wikidata-mcp-server@0.1.19"], runtime_type="node",
                working_directory=None, env_vars={"MCP_LOG_LEVEL": "warning"}, transport="stdio",
                auth_type="none", auth_schema={"fields": []},
                auth_config={**base, "auth_type": "none", "transport": "stdio", "credential_fields": [], "required_env": []},
            )
        )


def downgrade() -> None:
    # Not reversible — the cloned entry point never ran.
    pass
