"""add builder spend limits

Revision ID: a1c3e5f7b9d2
Revises: e7a9c1d3f5b8
Create Date: 2026-11-12 14:30:00.000000

builder_spend_limits: a person's own monthly limit on what their runs cost.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a1c3e5f7b9d2'
down_revision = 'e7a9c1d3f5b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('builder_spend_limits',
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('monthly_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('owner_id')
    )
    op.create_index(op.f('ix_builder_spend_limits_tenant_id'), 'builder_spend_limits', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_spend_limits_tenant_id'), table_name='builder_spend_limits')
    op.drop_table('builder_spend_limits')
