"""Request/response schemas for the builder tool-runtime API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolInvokeRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Required for tools that change data (risk edit/delete).
    confirm: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)


class ToolRiskOut(BaseModel):
    risk: Literal["read", "edit", "delete"]
    reason: str
    needs_confirmation: bool


class ToolInvokeResponse(BaseModel):
    server_id: str
    server_name: str
    tool_name: str
    risk: ToolRiskOut
    is_error: bool
    text: str
    structured: Any = None
    content: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    duration_ms: int
    attempts: int


class RuntimeToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] | None = None
    risk: ToolRiskOut


class ServerToolsResponse(BaseModel):
    server_id: str
    server_name: str
    connected: bool
    tools: list[RuntimeToolOut]
