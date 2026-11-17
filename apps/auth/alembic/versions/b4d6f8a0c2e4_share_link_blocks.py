"""share links: people the publisher blocked

Revision ID: b4d6f8a0c2e4
Revises: a3c5e7f9b1d2
Create Date: 2026-10-20 12:00:00.000000

builder_public_keys.blocked_user_ids: who may no longer start runs from the
key's share link (they still see their earlier ones).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b4d6f8a0c2e4'
down_revision = 'a3c5e7f9b1d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('builder_public_keys', sa.Column('blocked_user_ids', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('builder_public_keys', 'blocked_user_ids')
