"""Tenant management & member CRUD schemas."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TenantStats(BaseModel):
    workspace_count: int
    member_count: int


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class MemberCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "tenant_user"


class MemberUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None