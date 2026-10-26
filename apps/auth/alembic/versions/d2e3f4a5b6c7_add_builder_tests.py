"""add builder tests

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-09 18:00:00.000000

Testing agents and workflows: saved test cases, test runs (one per run of a
set of cases against one version) and their per-case results; and
builder_runs.purpose so a test case's run is told apart from a real one.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table('builder_test_cases',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('input', sa.Text(), nullable=False),
    sa.Column('variables', sa.JSON(), nullable=False),
    sa.Column('expectation', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    *_stamps(),
    sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['builder_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_test_cases_agent_id'), 'builder_test_cases', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_test_cases_tenant_id'), 'builder_test_cases', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_test_cases_workflow_id'), 'builder_test_cases', ['workflow_id'], unique=False)

    op.create_table('builder_test_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('definition_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('passed', sa.Integer(), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('dimensions', sa.JSON(), nullable=False),
    sa.Column('judge_tokens', sa.Integer(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    *_stamps(),
    sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['builder_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_test_runs_agent_id'), 'builder_test_runs', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_test_runs_owner_id'), 'builder_test_runs', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_test_runs_status'), 'builder_test_runs', ['status'], unique=False)
    op.create_index(op.f('ix_builder_test_runs_tenant_id'), 'builder_test_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_test_runs_workflow_id'), 'builder_test_runs', ['workflow_id'], unique=False)

    op.create_table('builder_test_results',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('test_run_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=True),
    sa.Column('run_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('input', sa.Text(), nullable=False),
    sa.Column('expectation', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('reasoning', sa.Text(), nullable=True),
    sa.Column('answer', sa.Text(), nullable=True),
    *_stamps(),
    sa.ForeignKeyConstraint(['test_run_id'], ['builder_test_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_test_results_run_id'), 'builder_test_results', ['run_id'], unique=False)
    op.create_index(op.f('ix_builder_test_results_status'), 'builder_test_results', ['status'], unique=False)
    op.create_index(op.f('ix_builder_test_results_test_run_id'), 'builder_test_results', ['test_run_id'], unique=False)

    op.add_column('builder_runs', sa.Column('purpose', sa.String(length=20), server_default='run', nullable=False))
    op.create_index(op.f('ix_builder_runs_purpose'), 'builder_runs', ['purpose'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_runs_purpose'), table_name='builder_runs')
    with op.batch_alter_table('builder_runs') as batch:
        batch.drop_column('purpose')
    op.drop_table('builder_test_results')
    op.drop_table('builder_test_runs')
    op.drop_table('builder_test_cases')
