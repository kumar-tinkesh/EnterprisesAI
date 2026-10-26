"""LinkedIn MCP servers ask for the li_at cookie, not PROXY_*

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-10-18 00:00:00.000000

Repo analysis read stickerdaniel/linkedin-mcp-server's README and registered
PROXY_USERNAME / PROXY_PASSWORD as its credentials. They are an optional
proxy (a proxy password without a proxy server makes the server exit at
start), and the connect forms read these columns before anything runs, so
nobody was ever asked for the one thing it needs: the li_at cookie. Rows
registered from now on get it at analysis
(vendor.services.mcp_auth.linkedin.apply_to_analysis); this fixes the ones
already there. No schema change.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None

REPO = "stickerdaniel/linkedin-mcp-server"
FIELD = {"name": "LI_AT", "label": "LinkedIn li_at cookie", "type": "secret", "required": True, "location": "env"}

_servers = sa.table(
    "vendor_mcp_servers",
    sa.column("id", sa.String),
    sa.column("source_repo_url", sa.String),
    sa.column("source_repo", sa.String),
    sa.column("server_url", sa.String),
    sa.column("auth_type", sa.String),
    sa.column("auth_config", sa.JSON),
    sa.column("auth_schema", sa.JSON),
    sa.column("env_vars", sa.JSON),
    sa.column("transport", sa.String),
)


def _json(raw) -> dict:
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_servers.c.id, _servers.c.source_repo_url, _servers.c.source_repo, _servers.c.server_url, _servers.c.auth_config)
    ).fetchall()
    for row_id, repo_url, repo, server_url, auth_config_raw in rows:
        if not any(REPO in (p or "").lower() for p in (repo_url, repo, server_url)):
            continue
        auth_config = {
            **_json(auth_config_raw),
            "auth_type": "linkedin_cookie",
            "transport": "stdio",
            "credential_fields": [FIELD],
            "required_env": [],
        }
        bind.execute(
            _servers.update().where(_servers.c.id == row_id).values(
                auth_type="linkedin_cookie", auth_config=auth_config, auth_schema={"fields": [FIELD]},
                env_vars={}, transport="stdio",
            )
        )


def downgrade() -> None:
    # Not reversible — the PROXY_* fields never worked.
    pass
