"""add builder public keys

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-09 21:00:00.000000

Publishing agents and workflows: publishable keys (builder_public_keys, only a
hash of each key is stored) and builder_runs.public_key_id for the runs they start.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('builder_public_keys',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('allowed_origins', sa.JSON(), nullable=False),
    sa.Column('requests_per_minute', sa.Integer(), nullable=False),
    sa.Column('daily_quota', sa.Integer(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['builder_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_public_keys_agent_id'), 'builder_public_keys', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_public_keys_key_hash'), 'builder_public_keys', ['key_hash'], unique=True)
    op.create_index(op.f('ix_builder_public_keys_owner_id'), 'builder_public_keys', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_public_keys_tenant_id'), 'builder_public_keys', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_public_keys_workflow_id'), 'builder_public_keys', ['workflow_id'], unique=False)

    op.add_column('builder_runs', sa.Column('public_key_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_builder_runs_public_key_id'), 'builder_runs', ['public_key_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_runs_public_key_id'), table_name='builder_runs')
    with op.batch_alter_table('builder_runs') as batch:
        batch.drop_column('public_key_id')
    op.drop_table('builder_public_keys')
