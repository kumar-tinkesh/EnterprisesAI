"""Shared API response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class MessageResponse(BaseModel):
    detail: str


class JwksResponse(BaseModel):
    keys: list[dict[str, Any]]