"""Shared API response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class MessageResponse(BaseModel):
    detail: str


class UserInfo(BaseModel):
    id: str
    email: str
    full_name: str
    tenant_id: str | None = None
    auth_provider: str
    roles: list[str] = []


class JwksResponse(BaseModel):
    keys: list[dict[str, Any]]