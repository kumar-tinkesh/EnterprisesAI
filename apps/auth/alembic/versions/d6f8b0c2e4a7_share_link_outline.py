"""share links: show how it works

Revision ID: d6f8b0c2e4a7
Revises: c5e7a9b1d3f6
Create Date: 2026-10-23 16:00:00.000000

builder_public_keys.show_outline: the share link page may show what the
agent/workflow does step by step (names, kinds and apps only) and each run's
steps as they go. On by default; the publisher can turn it off.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd6f8b0c2e4a7'
down_revision = 'c5e7a9b1d3f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('builder_public_keys', sa.Column('show_outline', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('builder_public_keys', 'show_outline')
