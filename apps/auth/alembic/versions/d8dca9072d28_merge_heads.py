"""merge heads

Revision ID: d8dca9072d28
Revises: 20260902080418, a7b8c9d0e1f2
Create Date: 2026-09-02 16:36:13.364191
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd8dca9072d28'
down_revision = ('20260902080418', 'a7b8c9d0e1f2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass