"""refresh_tokens.replaced_by holds a SHA-256 hex hash: 64 characters, not 36

Revision ID: e7a9c1d3f5b8
Revises: d6f8b0c2e4a7
Create Date: 2026-10-23 19:00:00.000000

Rotating a refresh token stores the new token's hash here. SQLite never
checked the length, so it worked there; on Postgres the 64-character hash
didn't fit in VARCHAR(36) and refreshing a session failed.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e7a9c1d3f5b8'
down_revision = 'd6f8b0c2e4a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('refresh_tokens') as batch:
        batch.alter_column('replaced_by', existing_type=sa.String(length=36), type_=sa.String(length=64), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('refresh_tokens') as batch:
        batch.alter_column('replaced_by', existing_type=sa.String(length=64), type_=sa.String(length=36), existing_nullable=True)
