"""jimsimoy/gmail-mcp servers connect with a Google sign-in

Revision ID: 6a1f3c9e2b7d
Revises: a2b3c4d5e6f7
Create Date: 2026-10-18 00:00:00.000000

Repo analysis registered jimsimoy/gmail-mcp with five env fields — the OAuth
client's ID and secret, GMAIL_REFRESH_TOKEN, and two tool arguments (DRAFT_ID,
THREAD_ID) — so nobody without a refresh token in hand could connect it, and
it failed to start without one. It is an OAuth server now, with Google's fixed
endpoints (vendor.services.known_servers): the admin gives the client ID and
secret, each person signs in with Google, and the refresh token comes from
that. No schema change.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "6a1f3c9e2b7d"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

REPO = "jimsimoy/gmail-mcp"
FIELDS = [
    {"name": "GMAIL_CLIENT_ID", "label": "Google OAuth Client ID", "type": "string", "required": True, "location": "env"},
    {"name": "GMAIL_CLIENT_SECRET", "label": "Google OAuth Client Secret", "type": "secret", "required": True, "location": "env"},
]
OAUTH = {
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "scopes_supported": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
    ],
    "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
}

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
                env_vars={"GMAIL_ACCESS_LEVEL": "FULL"}, auth_type="oauth2", auth_schema={"fields": FIELDS},
                auth_config={**base, "auth_type": "oauth2", "transport": "stdio", "credential_fields": FIELDS,
                             "required_env": [], "oauth": OAUTH},
            )
        )


def downgrade() -> None:
    # Not reversible — the old fields could never start the server without a token from elsewhere.
    pass
