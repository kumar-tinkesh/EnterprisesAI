"""add knowledge bases

Revision ID: e7a1c9d4b2f0
Revises: c8e2a6f13d90
Create Date: 2026-10-07 12:00:00.000000

Adds the knowledge domain (``apps/backend/knowledge``): tenant-scoped
``knowledge_bases``, their ``knowledge_documents``, and the embedded
``knowledge_chunks`` retrieval ranks. Embeddings are portable ``sa.JSON()``
(list[float]) like ``vendor_mcp_tools.embedding`` — SQLite-safe, no pgvector.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

# revision identifiers, used by Alembic.
revision = "e7a1c9d4b2f0"
down_revision = "c8e2a6f13d90"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"])
    op.create_index("ix_knowledge_bases_owner_id", "knowledge_bases", ["owner_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_documents_knowledge_base_id", "knowledge_documents", ["knowledge_base_id"])
    op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_knowledge_base_id", "knowledge_chunks", ["knowledge_base_id"])
    op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_tenant_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_knowledge_base_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_tenant_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_knowledge_base_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_knowledge_bases_owner_id", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_tenant_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
