"""ORM models for the knowledge domain.

Registered on the shared ``src.db.base.Base`` metadata (same as
``vendor.models``) so Alembic and the ``create_all`` fallback see them.

Embeddings are stored as ``JSON`` (``list[float]``), not pgvector, so the
schema is portable across SQLite and PostgreSQL; ``embedding_model`` lets
retrieval skip vectors produced by a different model than the query's.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin
from src.models.tenant import uuid_str


class KnowledgeBase(Base, TimestampMixin):
    """A named collection of documents, shared by every member of a tenant."""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")


class KnowledgeDocument(Base, TimestampMixin):
    """One ingested source: an uploaded file or text typed in the UI."""

    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    filename: Mapped[str] = mapped_column(String(1024))
    # processing | ready | error
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The whole text of a document typed in the UI or uploaded as .md/.txt,
    # kept so it can be edited and re-indexed. NULL for binary uploads.
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class KnowledgeChunk(Base, TimestampMixin):
    """A chunk of a document plus its embedding."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


__all__ = ["KnowledgeBase", "KnowledgeDocument", "KnowledgeChunk"]
