"""Pydantic v2 request/response contracts for the User domain API.

Re-exports all schemas from ``user.api.schemas`` for backward compatibility.
"""
from __future__ import annotations

from user.api.schemas import (
    CatalogEntry,
    CatalogResponse,
    PlannedToolCall,
    ToolCallPlanResponse,
    ToolSearchResponse,
    ToolSearchResult,
)

__all__ = [
    "CatalogEntry",
    "CatalogResponse",
    "ToolSearchResult",
    "ToolSearchResponse",
    "PlannedToolCall",
    "ToolCallPlanResponse",
]
