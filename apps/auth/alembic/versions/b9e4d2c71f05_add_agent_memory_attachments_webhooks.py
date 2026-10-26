"""add agent memory, attachments, webhooks and run cost

Revision ID: b9e4d2c71f05
Revises: f4a5b6c7d8e9
Create Date: 2026-10-14 12:00:00.000000

builder_agent_memories (what an agent remembers about a person),
builder_attachments (files sent with a chat message), builder_webhooks (URLs
that run an agent) and builder_runs.cost_usd/webhook_id.

Idempotent: the API falls back to ``create_all`` when an upgrade fails, which
creates new tables (not new columns) — so each table, column and index is
added only if it isn't there yet.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b9e4d2c71f05'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    tables = _tables()
    if 'builder_agent_memories' not in tables:
        op.create_table('builder_agent_memories',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('agent_id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_run_id', sa.String(length=36), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    _index(op.f('ix_builder_agent_memories_tenant_id'), 'builder_agent_memories', ['tenant_id'])
    _index(op.f('ix_builder_agent_memories_owner_id'), 'builder_agent_memories', ['owner_id'])
    _index('ix_builder_agent_memories_agent_owner', 'builder_agent_memories', ['agent_id', 'owner_id'])

    if 'builder_attachments' not in tables:
        op.create_table('builder_attachments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('data', sa.LargeBinary(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint('id')
        )
    _index(op.f('ix_builder_attachments_tenant_id'), 'builder_attachments', ['tenant_id'])
    _index(op.f('ix_builder_attachments_owner_id'), 'builder_attachments', ['owner_id'])

    if 'builder_webhooks' not in tables:
        op.create_table('builder_webhooks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('agent_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('token_prefix', sa.String(length=20), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('requests_per_minute', sa.Integer(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_id', sa.String(length=36), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    _index(op.f('ix_builder_webhooks_tenant_id'), 'builder_webhooks', ['tenant_id'])
    _index(op.f('ix_builder_webhooks_owner_id'), 'builder_webhooks', ['owner_id'])
    _index(op.f('ix_builder_webhooks_agent_id'), 'builder_webhooks', ['agent_id'])
    _index(op.f('ix_builder_webhooks_token_hash'), 'builder_webhooks', ['token_hash'], unique=True)

    run_cols = _columns('builder_runs')
    if 'cost_usd' not in run_cols:
        op.add_column('builder_runs', sa.Column('cost_usd', sa.Float(), nullable=True))
    if 'webhook_id' not in run_cols:
        op.add_column('builder_runs', sa.Column('webhook_id', sa.String(length=36), nullable=True))
    _index(op.f('ix_builder_runs_webhook_id'), 'builder_runs', ['webhook_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_runs_webhook_id'), table_name='builder_runs')
    with op.batch_alter_table('builder_runs') as batch:
        batch.drop_column('webhook_id')
        batch.drop_column('cost_usd')
    op.drop_table('builder_webhooks')
    op.drop_table('builder_attachments')
    op.drop_table('builder_agent_memories')
