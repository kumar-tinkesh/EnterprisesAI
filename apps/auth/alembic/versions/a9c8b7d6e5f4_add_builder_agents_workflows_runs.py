"""add builder agents workflows runs

Revision ID: a9c8b7d6e5f4
Revises: f1b2c3d4e5a6
Create Date: 2026-10-07 19:24:10.618852

The builder domain (apps/backend/builder/models.py): tenant-shared agents and
workflows, and the durable run records — runs (with a frozen definition and a
worker lease), one row per node attempt, a ledger of every tool call written
before it is sent, and the approvals a run waits on. Portable JSON columns,
no Postgres-only types. Pre-existing schema drift elsewhere (sso_configs,
refresh_tokens indexes, vendor_mcp_servers.server_url) is deliberately left
alone here.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a9c8b7d6e5f4'
down_revision = 'f1b2c3d4e5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('builder_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('definition_version', sa.Integer(), nullable=False),
    sa.Column('definition', sa.JSON(), nullable=False),
    sa.Column('input', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('output_text', sa.Text(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('lease_owner', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_runs_agent_id'), 'builder_runs', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_runs_owner_id'), 'builder_runs', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_runs_status'), 'builder_runs', ['status'], unique=False)
    op.create_index('ix_builder_runs_status_lease', 'builder_runs', ['status', 'lease_expires_at'], unique=False)
    op.create_index('ix_builder_runs_tenant_created', 'builder_runs', ['tenant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_builder_runs_tenant_id'), 'builder_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_runs_workflow_id'), 'builder_runs', ['workflow_id'], unique=False)
    op.create_table('builder_approvals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('node_id', sa.String(length=255), nullable=True),
    sa.Column('tool_call_id', sa.String(length=36), nullable=True),
    sa.Column('tool_name', sa.String(length=255), nullable=True),
    sa.Column('risk', sa.String(length=10), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('edited_input', sa.JSON(), nullable=True),
    sa.Column('resolved_by', sa.String(length=36), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['builder_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_approvals_owner_id'), 'builder_approvals', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_approvals_run_id'), 'builder_approvals', ['run_id'], unique=False)
    op.create_index(op.f('ix_builder_approvals_status'), 'builder_approvals', ['status'], unique=False)
    op.create_index(op.f('ix_builder_approvals_tenant_id'), 'builder_approvals', ['tenant_id'], unique=False)
    op.create_table('builder_node_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('node_id', sa.String(length=255), nullable=False),
    sa.Column('node_type', sa.String(length=50), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('input_text', sa.Text(), nullable=True),
    sa.Column('output_text', sa.Text(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['builder_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'node_id', 'attempt', name='uq_builder_node_run_attempt')
    )
    op.create_index(op.f('ix_builder_node_runs_run_id'), 'builder_node_runs', ['run_id'], unique=False)
    op.create_table('builder_tool_calls',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('node_run_id', sa.String(length=36), nullable=True),
    sa.Column('node_id', sa.String(length=255), nullable=True),
    sa.Column('call_key', sa.String(length=255), nullable=False),
    sa.Column('server_id', sa.String(length=36), nullable=False),
    sa.Column('tool_name', sa.String(length=255), nullable=False),
    sa.Column('risk', sa.String(length=10), nullable=False),
    sa.Column('arguments', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('result_text', sa.Text(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('is_error', sa.Boolean(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('approval_id', sa.String(length=36), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['builder_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'call_key', name='uq_builder_tool_call_key')
    )
    op.create_index(op.f('ix_builder_tool_calls_node_run_id'), 'builder_tool_calls', ['node_run_id'], unique=False)
    op.create_index(op.f('ix_builder_tool_calls_run_id'), 'builder_tool_calls', ['run_id'], unique=False)
    op.create_table('builder_workflows',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('nodes', sa.JSON(), nullable=False),
    sa.Column('edges', sa.JSON(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_workflows_owner_id'), 'builder_workflows', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_workflows_tenant_id'), 'builder_workflows', ['tenant_id'], unique=False)
    op.create_table('builder_agents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=255), nullable=False),
    sa.Column('goal', sa.Text(), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=False),
    sa.Column('llm_provider', sa.String(length=50), nullable=False),
    sa.Column('llm_model', sa.String(length=100), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['builder_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_agents_owner_id'), 'builder_agents', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_agents_tenant_id'), 'builder_agents', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_agents_workflow_id'), 'builder_agents', ['workflow_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_agents_workflow_id'), table_name='builder_agents')
    op.drop_index(op.f('ix_builder_agents_tenant_id'), table_name='builder_agents')
    op.drop_index(op.f('ix_builder_agents_owner_id'), table_name='builder_agents')
    op.drop_table('builder_agents')
    op.drop_index(op.f('ix_builder_workflows_tenant_id'), table_name='builder_workflows')
    op.drop_index(op.f('ix_builder_workflows_owner_id'), table_name='builder_workflows')
    op.drop_table('builder_workflows')
    op.drop_index(op.f('ix_builder_tool_calls_run_id'), table_name='builder_tool_calls')
    op.drop_index(op.f('ix_builder_tool_calls_node_run_id'), table_name='builder_tool_calls')
    op.drop_table('builder_tool_calls')
    op.drop_index(op.f('ix_builder_node_runs_run_id'), table_name='builder_node_runs')
    op.drop_table('builder_node_runs')
    op.drop_index(op.f('ix_builder_approvals_tenant_id'), table_name='builder_approvals')
    op.drop_index(op.f('ix_builder_approvals_status'), table_name='builder_approvals')
    op.drop_index(op.f('ix_builder_approvals_run_id'), table_name='builder_approvals')
    op.drop_index(op.f('ix_builder_approvals_owner_id'), table_name='builder_approvals')
    op.drop_table('builder_approvals')
    op.drop_index(op.f('ix_builder_runs_workflow_id'), table_name='builder_runs')
    op.drop_index(op.f('ix_builder_runs_tenant_id'), table_name='builder_runs')
    op.drop_index('ix_builder_runs_tenant_created', table_name='builder_runs')
    op.drop_index('ix_builder_runs_status_lease', table_name='builder_runs')
    op.drop_index(op.f('ix_builder_runs_status'), table_name='builder_runs')
    op.drop_index(op.f('ix_builder_runs_owner_id'), table_name='builder_runs')
    op.drop_index(op.f('ix_builder_runs_agent_id'), table_name='builder_runs')
    op.drop_table('builder_runs')
    # ### end Alembic commands ###