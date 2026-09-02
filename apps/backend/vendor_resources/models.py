"""SQLAlchemy 2.0 ORM models for the Vendor Resources subsystem.

All models inherit the shared :class:`~src.db.base.Base` and
:class:`~src.db.base.TimestampMixin` (reused from the Auth service via absolute
imports), so they attach to the *same* ``Base.metadata`` as the auth tables and
live in the single centralized database.

Phase 1 defines only ``vendor_mcp_servers`` and ``tenant_resource_grants``.
The ``resource_type`` string on grants already accommodates ``datasource``
values added in later phases without a schema change.

NOTE: SQLite (the default dev DB) has no ``JSONB`` / ``pgvector`` —
``bound_tools`` uses portable ``sqlalchemy.JSON``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin


def uuid_str() -> str:
    return str(uuid.uuid4())


class VendorMCPServer(Base, TimestampMixin):
    """A registered MCP Server (SSE or Stdio transport)."""

    __tablename__ = "vendor_mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transport: Mapped[str] = mapped_column(String(32), nullable=False, default="sse")
    server_url: Mapped[str] = mapped_column(String(512), nullable=False)
    bound_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Detected credential requirement for this server (from mcp_detect):
    # {"auth_type": "none|api_key|bearer|basic|oauth2|env",
    #  "credential_fields": [{name, label, type, placeholder, secret, required}],
    #  "transport": ..., "confidence": ..., "hints": [...]}
    auth_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_global: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)


class VendorMCPCredential(Base, TimestampMixin):
    """Encrypted credentials for an MCP server (vendor-level or per-tenant).

    ``encrypted_credentials`` holds a Fernet-encrypted JSON blob of the
    credential fields (API keys, basic passwords, OAuth client secrets and
    refresh tokens). ``tenant_id IS NULL`` marks vendor-level credentials;
    a per-tenant row overrides the vendor-level fallback. Managed by
    ``vendor_resources.services.mcp_auth``.
    """

    __tablename__ = "vendor_mcp_credentials"
    __table_args__ = (
        Index("ix_vmc_server_tenant", "server_id", "tenant_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    server_id: Mapped[str] = mapped_column(
        ForeignKey("vendor_mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)


class TenantResourceGrant(Base, TimestampMixin):
    """Maps a Vendor Resource (mcp / datasource) to a Tenant.

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