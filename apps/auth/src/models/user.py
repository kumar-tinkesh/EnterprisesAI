"""Tenant user model (local + OIDC / SSO)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models.tenant import uuid_str


class User(Base, TimestampMixin):
    """A user inside a tenant, optionally provisioned via an OIDC provider.

    ``oidc_sub`` stores the provider's unique subject id for SSO linkage; when
    present, password login is skipped for that user.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Role in the three-tier model: "tenant_admin" | "tenant_user".
    role: Mapped[str] = mapped_column(String(32), default="tenant_user")

    # SSO linkage
    auth_provider: Mapped[str] = mapped_column(String(32), default="local")
    oidc_sub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    memberships: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )