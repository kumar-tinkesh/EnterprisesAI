"""drop is_superuser from vendor_users

Revision ID: a1b2c3d4e5f6
Revises: 5b2dfbe1786e
Create Date: 2026-08-29 10:05:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '5b2dfbe1786e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot drop a column natively; use batch mode there.
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('vendor_users') as batch_op:
            batch_op.drop_column('is_superuser')
    else:
        op.drop_column('vendor_users', 'is_superuser')


def downgrade() -> None:
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('vendor_users') as batch_op:
            batch_op.add_column(
                sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            )
    else:
        op.add_column(
            'vendor_users',
            sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        )
