"""workspaces: a description, and builder data that belongs to one

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-11-24 17:00:00.000000

workspaces.description: a line about what the workspace is for.

workspace_id on the builder's top-level rows (agents, workflows, runs,
conversations, approvals, schedules, share links, webhooks) and on knowledge
bases. A tenant with several workspaces sees in each only what was made there.
Existing rows go to their tenant's first active workspace — until now every
tenant had just one in practice, so nothing moves out of sight.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b2d4f6a8c0e1'
down_revision = 'a1c3e5f7b9d2'
branch_labels = None
depends_on = None

TABLES = (
    'builder_agents',
    'builder_workflows',
    'builder_runs',
    'builder_conversations',
    'builder_approvals',
    'builder_schedules',
    'builder_public_keys',
    'builder_webhooks',
    'knowledge_bases',
)


def upgrade() -> None:
    with op.batch_alter_table('workspaces') as batch:
        batch.add_column(sa.Column('description', sa.String(length=500), nullable=True))

    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('workspace_id', sa.String(length=36), nullable=True))
            batch.create_index(f'ix_{table}_workspace_id', ['workspace_id'])
        op.execute(
            f"""
            UPDATE {table} SET workspace_id = (
                SELECT w.id FROM workspaces w
                WHERE w.tenant_id = {table}.tenant_id AND w.status = 'active'
                ORDER BY w.created_at, w.id
                LIMIT 1
            )
            WHERE workspace_id IS NULL
            """
        )


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f'ix_{table}_workspace_id')
            batch.drop_column('workspace_id')
    with op.batch_alter_table('workspaces') as batch:
        batch.drop_column('description')
