"""add builder schedules

Revision ID: b7c8d9e0f1a2
Revises: a9c8b7d6e5f4
Create Date: 2026-10-09 12:30:00.000000

Cron schedules for builder agents and workflows (builder_schedules), and
builder_runs.schedule_id so run history shows which runs a schedule started.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7c8d9e0f1a2'
down_revision = 'a9c8b7d6e5f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('builder_schedules',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('node_id', sa.String(length=255), nullable=True),
    sa.Column('cron', sa.String(length=100), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('input', sa.JSON(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_id', sa.String(length=36), nullable=True),
    sa.Column('last_status', sa.String(length=20), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['builder_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'node_id', name='uq_builder_schedule_workflow_node')
    )
    op.create_index('ix_builder_schedules_due', 'builder_schedules', ['enabled', 'next_run_at'], unique=False)
    op.create_index(op.f('ix_builder_schedules_agent_id'), 'builder_schedules', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_schedules_owner_id'), 'builder_schedules', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_schedules_tenant_id'), 'builder_schedules', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_schedules_workflow_id'), 'builder_schedules', ['workflow_id'], unique=False)

    op.add_column('builder_runs', sa.Column('schedule_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_builder_runs_schedule_id'), 'builder_runs', ['schedule_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_runs_schedule_id'), table_name='builder_runs')
    with op.batch_alter_table('builder_runs') as batch:
        batch.drop_column('schedule_id')

    op.drop_index(op.f('ix_builder_schedules_workflow_id'), table_name='builder_schedules')
    op.drop_index(op.f('ix_builder_schedules_tenant_id'), table_name='builder_schedules')
    op.drop_index(op.f('ix_builder_schedules_owner_id'), table_name='builder_schedules')
    op.drop_index(op.f('ix_builder_schedules_agent_id'), table_name='builder_schedules')
    op.drop_index('ix_builder_schedules_due', table_name='builder_schedules')
    op.drop_table('builder_schedules')
