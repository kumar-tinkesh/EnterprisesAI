"""Earlier runs started from the editor become chats of their own

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-10-18 00:00:00.000000

Runs started from the workflow editor (its Run button and its playground) or
the agent playground had no chat, so they never showed in Executions → Chat
history. They start one each from now on; this gives every earlier such run —
a person's own run (purpose "run"), not a scheduled or webhook one — a chat
of its own, titled from what it was asked. No schema change.
"""
from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

TITLE_CHARS = 80

_runs = sa.table(
    "builder_runs",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("owner_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("agent_id", sa.String),
    sa.column("workflow_id", sa.String),
    sa.column("input", sa.JSON),
    sa.column("purpose", sa.String),
    sa.column("conversation_id", sa.String),
    sa.column("schedule_id", sa.String),
    sa.column("webhook_id", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_chats = sa.table(
    "builder_conversations",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("owner_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("agent_id", sa.String),
    sa.column("workflow_id", sa.String),
    sa.column("title", sa.String),
    sa.column("turn_count", sa.Integer),
    sa.column("last_message_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _title(raw_input) -> str:
    data = raw_input if isinstance(raw_input, dict) else json.loads(raw_input or "{}")
    line = " ".join(str(data.get("text") or "").split())
    if not line and data.get("variables"):
        line = " · ".join(str(v) for v in data["variables"].values() if v)
    line = line or "Run"
    return line if len(line) <= TITLE_CHARS else line[:TITLE_CHARS] + "…"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            _runs.c.id, _runs.c.tenant_id, _runs.c.owner_id, _runs.c.kind, _runs.c.agent_id, _runs.c.workflow_id,
            _runs.c.input, _runs.c.created_at,
        ).where(
            _runs.c.conversation_id.is_(None), _runs.c.purpose == "run",
            _runs.c.schedule_id.is_(None), _runs.c.webhook_id.is_(None),
            _runs.c.kind.in_(("agent", "workflow")),
        )
    ).fetchall()
    for run_id, tenant_id, owner_id, kind, agent_id, workflow_id, raw_input, created_at in rows:
        chat_id = str(uuid.uuid4())
        bind.execute(_chats.insert().values(
            id=chat_id, tenant_id=tenant_id, owner_id=owner_id, kind=kind, agent_id=agent_id, workflow_id=workflow_id,
            title=_title(raw_input), turn_count=1, last_message_at=created_at, created_at=created_at, updated_at=created_at,
        ))
        bind.execute(_runs.update().where(_runs.c.id == run_id).values(conversation_id=chat_id))


def downgrade() -> None:
    # The chats stay: they hold nothing the runs don't, and deleting a chat deletes its runs.
    pass
