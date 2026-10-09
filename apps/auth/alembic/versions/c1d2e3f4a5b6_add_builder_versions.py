"""add builder versions

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-10-09 15:00:00.000000

Version history for builder agents and workflows (builder_versions): one full
snapshot per save, so an earlier state can be previewed and restored.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('builder_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('note', sa.String(length=255), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('author_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['builder_agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['builder_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'version', name='uq_builder_version_agent'),
    sa.UniqueConstraint('workflow_id', 'version', name='uq_builder_version_workflow')
    )
    op.create_index(op.f('ix_builder_versions_agent_id'), 'builder_versions', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_versions_tenant_id'), 'builder_versions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_versions_workflow_id'), 'builder_versions', ['workflow_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_versions_workflow_id'), table_name='builder_versions')
    op.drop_index(op.f('ix_builder_versions_tenant_id'), table_name='builder_versions')
    op.drop_index(op.f('ix_builder_versions_agent_id'), table_name='builder_versions')
    op.drop_table('builder_versions')
