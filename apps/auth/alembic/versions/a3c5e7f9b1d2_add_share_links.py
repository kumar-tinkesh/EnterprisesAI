"""add share links to publishable keys

Revision ID: a3c5e7f9b1d2
Revises: 6a1f3c9e2b7d
Create Date: 2026-10-20 00:00:00.000000

A publishable key can also have a share link (/r/{share_slug}): anyone who
signs in may run it there, with the publisher's tools (tool_mode), up to
per_user_daily_limit runs a day each. builder_runs.caller_user_id is who
started a run that way, so each person sees only their own.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a3c5e7f9b1d2'
down_revision = '6a1f3c9e2b7d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('builder_public_keys', sa.Column('share_slug', sa.String(length=32), nullable=True))
    op.add_column('builder_public_keys', sa.Column('share_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('builder_public_keys', sa.Column('tool_mode', sa.String(length=20), nullable=False, server_default='publisher'))
    op.add_column('builder_public_keys', sa.Column('per_user_daily_limit', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_builder_public_keys_share_slug'), 'builder_public_keys', ['share_slug'], unique=True)
    op.add_column('builder_runs', sa.Column('caller_user_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_builder_runs_caller_user_id'), 'builder_runs', ['caller_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_runs_caller_user_id'), table_name='builder_runs')
    op.drop_column('builder_runs', 'caller_user_id')
    op.drop_index(op.f('ix_builder_public_keys_share_slug'), table_name='builder_public_keys')
    op.drop_column('builder_public_keys', 'per_user_daily_limit')
    op.drop_column('builder_public_keys', 'tool_mode')
    op.drop_column('builder_public_keys', 'share_enabled')
    op.drop_column('builder_public_keys', 'share_slug')
