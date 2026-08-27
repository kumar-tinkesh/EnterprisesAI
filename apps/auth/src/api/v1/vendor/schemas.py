"""Vendor management & platform stats schemas."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class VendorStats(BaseModel):
    total_tenants: int
    individual_users: int
    total_users: int
    total_workspaces: int


class VendorTenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    status: str
    is_personal: bool
    created_at: datetime
    admin_email: str | None = None
    admin_name: str | None = None
    user_count: int = 0
    workspace_count: int = 0


class VendorTenantCreate(BaseModel):
    name: str
    slug: str | None = None
    admin_email: str
    admin_full_name: str
    admin_password: str


class VendorTenantUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
