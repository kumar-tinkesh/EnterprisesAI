"""Vendor / Tenant / SSO-configuration models (3-tier auth, top two tiers)."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


def uuid_str() -> str:
    return str(uuid.uuid4())


class VendorUser(Base, TimestampMixin):
    """Platform-level user (Vendor / PlatformAdmin)."""

    __tablename__ = "vendor_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Role in the three-tier model: always "vendor_admin" for now.
    role: Mapped[str] = mapped_column(String(32), default="vendor_admin")

    tenants: Mapped[list["Tenant"]] = relationship(back_populates="vendor_user")


class Tenant(Base, TimestampMixin):
    """A tenant (organisation) under which workspaces and users live.

    When ``is_personal`` is True the tenant was auto-created for a solo user
    and should be hidden from admin tenant listings.
    """

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False)
    vendor_user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vendor_users.id", ondelete="SET NULL"), nullable=True
    )

    vendor_user: Mapped[Optional[VendorUser]] = relationship(back_populates="tenants")
    workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )