"""SQLAlchemy 2.0 ORM models for the Vendor Resources subsystem.

All models inherit the shared :class:`~src.db.base.Base` and
:class:`~src.db.base.TimestampMixin` (reused from the Auth service via absolute
imports), so they attach to the *same* ``Base.metadata`` as the auth tables and
live in the single centralized database.

Phase 1 defines only ``vendor_tools`` and ``tenant_resource_grants``. The
``resource_type`` string on grants already accommodates ``mcp_server`` /
``data_source`` values added in later phases without a schema change.

NOTE: SQLite (the default dev DB) has no ``JSONB`` / ``pgvector`` —
``parameters_schema`` uses portable ``sqlalchemy.JSON``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin


def uuid_str() -> str:
    return str(uuid.uuid4())


class VendorTool(Base, TimestampMixin):
    """A declarative REST API / OpenAPI tool registered by a Vendor Admin."""

    __tablename__ = "vendor_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="POST")
    endpoint_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parameters_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_global: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    vault_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TenantResourceGrant(Base, TimestampMixin):
    """Maps a Vendor Resource (tool / mcp / datasource) to a Tenant.

    All members of the granted tenant inherit access automatically.
    """

    __tablename__ = "tenant_resource_grants"
    __table_args__ = (
        Index(
            "ix_grant_tenant_resource",
            "tenant_id",
            "resource_type",
            "resource_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)


class ToolEmbedding(Base, TimestampMixin):
    """A single embedding vector for a vendor tool (semantic catalog matching).

    One row per tool (unique ``tool_id``); cascade-deleted with the tool.
    Stored as portable ``JSON`` (list[float]) so it works on SQLite without
    pgvector / sqlite-vec. The schema stays swappable to a native vector index
    later — only this model and the ranking code would change.
    """

    __tablename__ = "tool_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("vendor_tools.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    embedding: Mapped[list] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)