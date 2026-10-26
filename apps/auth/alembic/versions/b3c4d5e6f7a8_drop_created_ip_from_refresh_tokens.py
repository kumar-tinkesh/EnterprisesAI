"""drop created_ip from refresh_tokens

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-29 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot drop a column natively; use batch mode there.
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('refresh_tokens') as batch_op:
            batch_op.drop_column('created_ip')
    else:
        op.drop_column('refresh_tokens', 'created_ip')


def downgrade() -> None:
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('refresh_tokens') as batch_op:
            batch_op.add_column(
                sa.Column('created_ip', sa.String(length=64), nullable=True),
            )
    else:
        op.add_column(
            'refresh_tokens',
            sa.Column('created_ip', sa.String(length=64), nullable=True),
        )