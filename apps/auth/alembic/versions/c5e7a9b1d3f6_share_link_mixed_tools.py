"""share links: mixed tools

Revision ID: c5e7a9b1d3f6
Revises: b4d6f8a0c2e4
Create Date: 2026-10-20 18:00:00.000000

builder_public_keys.publisher_server_ids: on a "mixed" share link, the MCP
servers used with the publisher's account (and approved by them); every
other server is used with the visitor's own.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c5e7a9b1d3f6'
down_revision = 'b4d6f8a0c2e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('builder_public_keys', sa.Column('publisher_server_ids', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('builder_public_keys', 'publisher_server_ids')
