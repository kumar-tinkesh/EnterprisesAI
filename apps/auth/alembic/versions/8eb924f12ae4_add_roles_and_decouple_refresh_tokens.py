"""add roles and decouple refresh tokens

Revision ID: 8eb924f12ae4
Revises: 18ef1adda04f
Create Date: 2026-08-26 20:59:23.906287
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite


revision = '8eb924f12ae4'
down_revision = '18ef1adda04f'
branch_labels = None
depends_on = None


_REFRESH_COLS = [
    sa.Column('id', sa.String(length=36), primary_key=True),
    sa.Column('user_id', sa.String(length=36), nullable=False, index=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False, index=True, unique=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('replaced_by', sa.String(length=36), nullable=True),
    sa.Column('created_ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
]


_IDX = {'token_hash', 'user_id'}


def _pg_refresh_token_fk_names() -> list[str]:
    """Discover FK constraint names on refresh_tokens.user_id (Postgres).

    Alembic never named this constraint, so Postgres auto-named it; querying
    the catalog is the only reliable way to find the actual name.
    """
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f'
              AND t.relname = 'refresh_tokens'
              AND a.attname = 'user_id'
            """
        )
    ).fetchall()
    return [r[0] for r in rows]


def upgrade() -> None:
    # Role columns (server_default backfills existing rows).
    op.add_column('users', sa.Column('role', sa.String(length=32), nullable=False, server_default='tenant_user'))
    op.add_column('vendor_users', sa.Column('role', sa.String(length=32), nullable=False, server_default='vendor_admin'))

    if op.get_bind().dialect.name == 'sqlite':
        # Recreate refresh_tokens WITHOUT the legacy FK (SQLite can't drop it).
        op.create_table('refresh_tokens_new', *_REFRESH_COLS)
        op.execute(
            """INSERT INTO refresh_tokens_new
               (id, user_id, token_hash, expires_at, revoked, replaced_by,
                created_ip, user_agent, created_at, updated_at)
               SELECT id, user_id, token_hash, expires_at, revoked, replaced_by,
                      created_ip, user_agent, created_at, updated_at
               FROM refresh_tokens"""
        )
        op.drop_table('refresh_tokens')
        op.rename_table('refresh_tokens_new', 'refresh_tokens')
    else:
        # Index ix_refresh_tokens_user_id already exists from the initial
        # schema; ONLY the FK needs to go.
        for name in _pg_refresh_token_fk_names():
            op.drop_constraint(name, 'refresh_tokens', type_='foreignkey')


def downgrade() -> None:
    if op.get_bind().dialect.name == 'sqlite':
        _cols = list(_REFRESH_COLS)
        _cols[1] = sa.Column(
            'user_id',
            sa.String(length=36),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        )
        op.create_table('refresh_tokens_new', _cols)
        op.execute(
            """INSERT INTO refresh_tokens_new
                (id, user_id, token_hash, expires_at, revoked, replaced_by,
                 created_ip, user_agent, created_at, updated_at)
               SELECT id, user_id, token_hash, expires_at, revoked, replaced_by,
                      created_ip, user_agent, created_at, updated_at
               FROM refresh_tokens"""
        )
        op.drop_table('refresh_tokens')
        op.rename_table('refresh_tokens_new', 'refresh_tokens')
    else:
        op.create_foreign_key(
            'refresh_tokens_user_id_fkey', 'refresh_tokens', 'users',
            ['user_id'], ['id'], ondelete='CASCADE',
        )
    op.drop_column('vendor_users', 'role')
    op.drop_column('users', 'role')
