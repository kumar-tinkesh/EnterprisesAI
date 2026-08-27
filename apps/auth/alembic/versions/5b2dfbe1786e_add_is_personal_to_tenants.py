"""add_is_personal_to_tenants

Revision ID: 5b2dfbe1786e
Revises: 8eb924f12ae4
Create Date: 2026-08-27 17:53:40.561566
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5b2dfbe1786e'
down_revision = '8eb924f12ae4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tenants',
        sa.Column('is_personal', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )


def downgrade() -> None:
    op.drop_column('tenants', 'is_personal')