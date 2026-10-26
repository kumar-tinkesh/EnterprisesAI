"""add builder conversations

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-10-12 23:30:00.000000

Playground chats: builder_conversations (one chat with an agent or workflow)
and builder_runs.conversation_id (the chat a run is one message of).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('builder_conversations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('workflow_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('turn_count', sa.Integer(), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_builder_conversations_tenant_id'), 'builder_conversations', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_builder_conversations_owner_id'), 'builder_conversations', ['owner_id'], unique=False)
    op.create_index(op.f('ix_builder_conversations_agent_id'), 'builder_conversations', ['agent_id'], unique=False)
    op.create_index(op.f('ix_builder_conversations_workflow_id'), 'builder_conversations', ['workflow_id'], unique=False)
    op.create_index('ix_builder_conversations_owner_last', 'builder_conversations', ['owner_id', 'last_message_at'], unique=False)

    op.add_column('builder_runs', sa.Column('conversation_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_builder_runs_conversation_id'), 'builder_runs', ['conversation_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_builder_runs_conversation_id'), table_name='builder_runs')
    with op.batch_alter_table('builder_runs') as batch:
        batch.drop_column('conversation_id')
    op.drop_index('ix_builder_conversations_owner_last', table_name='builder_conversations')
    op.drop_index(op.f('ix_builder_conversations_workflow_id'), table_name='builder_conversations')
    op.drop_index(op.f('ix_builder_conversations_agent_id'), table_name='builder_conversations')
    op.drop_index(op.f('ix_builder_conversations_owner_id'), table_name='builder_conversations')
    op.drop_index(op.f('ix_builder_conversations_tenant_id'), table_name='builder_conversations')
    op.drop_table('builder_conversations')
