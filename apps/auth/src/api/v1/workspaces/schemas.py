"""Workspace schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.api.v1.auth.schemas import AccountOut


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str = ""
    status: str
    my_role: str
    is_member: bool
    member_count: int
    is_current: bool
    created_at: datetime


class WorkspaceList(BaseModel):
    workspaces: list[WorkspaceOut]
    current_id: str | None
    # What the UI may offer: a solo account gets neither.
    can_create: bool
    can_switch: bool


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "archived"] | None = None


class WorkspaceMemberOut(BaseModel):
    user_id: str
    email: str
    full_name: str
    tenant_role: str
    role: str
    is_active: bool
    added_at: datetime


class MemberAdd(BaseModel):
    user_id: str
    role: Literal["admin", "member"] = "member"


class MemberRole(BaseModel):
    role: Literal["admin", "member"]


class SwitchResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AccountOut
