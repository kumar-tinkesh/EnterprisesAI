"""Local auth schemas (unified register/login with role)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.core.roles import Roles


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)
    # vendor_admin | tenant_admin | tenant_user
    role: str = Roles.TENANT_USER
    tenant_name: str = Field(default="Default", min_length=1, max_length=255)

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if not Roles.is_valid(v):
            raise ValueError(f"role must be one of {Roles.ALL}")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    # Optional: disambiguate vendor vs tenant identities sharing an email.
    role: str | None = Field(default=None)
    workspace_id: str | None = Field(default=None)


class RefreshRequest(BaseModel):
    refresh_token: str


class AccountOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AccountOut


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str | None = None
    is_active: bool = True


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    tenant_id: str | None = None
    action: str
    resource: str
    detail: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime | None = None

