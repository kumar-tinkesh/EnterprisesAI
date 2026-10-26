"""Notion MCP servers ask for NOTION_TOKEN only

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-10-18 00:00:00.000000

Repo analysis registered makenotion/notion-mcp-server with two credential
fields, AUTH_TOKEN and NOTION_TOKEN. The server reads NOTION_TOKEN only, so a
person who filled in AUTH_TOKEN connected fine and then every call failed
("the authorization header is missing"). From now on the forms ask for
NOTION_TOKEN alone (vendor.services.known_servers), and an AUTH_TOKEN already
saved is passed on as NOTION_TOKEN at launch, so nobody has to reconnect.
No schema change.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None

REPO = "makenotion/notion-mcp-server"
FIELD = {"name": "NOTION_TOKEN", "label": "Notion integration token (ntn_…)", "type": "secret", "required": True, "location": "env"}

_servers = sa.table(
    "vendor_mcp_servers",
    sa.column("id", sa.String),
    sa.column("source_repo_url", sa.String),
    sa.column("source_repo", sa.String),
    sa.column("server_url", sa.String),
    sa.column("env_vars", sa.JSON),
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
                env_vars={}, auth_type="env", auth_schema={"fields": [FIELD]},
                auth_config={**base, "auth_type": "env", "transport": "stdio", "credential_fields": [FIELD], "required_env": []},
            )
        )


def downgrade() -> None:
    # Not reversible — the AUTH_TOKEN field never reached the server.
    pass
