"""Auth-related models: refresh token rotation table and audit events."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin
from src.models.tenant import uuid_str


class RefreshToken(Base, TimestampMixin):
    """Persisted refresh token (stores an SHA-256 digest of the raw token).

    ``user_id`` references the id of either a ``User`` (tenant account) or a
    ``VendorUser`` (platform admin) — hence no FK constraint.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # noqa: F821
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    replaced_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class AuditEvent(Base, TimestampMixin):
    """Security / audit trail entry."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_user_action", "user_id", "action"),
        Index("ix_audit_tenant_time", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)