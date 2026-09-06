"""Pydantic v2 request/response contracts for the User domain API.

Covers the access-filtered MCP catalog and the two-stage semantic tool
search / tool-call planning endpoints — everything gated behind
``get_current_user`` (any authenticated user, not just ``vendor_admin``).
Server registration/lifecycle contracts live in ``vendor.api.v1.schemas``
instead.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CatalogEntry(BaseModel):
    """An MCP server as seen by a consumer (never exposes secret refs)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    transport: str
    server_url: str
    bound_tools: list


class CatalogResponse(BaseModel):
    """The authorized catalog for the calling user (access-filtered)."""

    servers: list[CatalogEntry]
    count: int


class ToolSearchResult(BaseModel):
    """One tool match from the two-stage semantic tool search.

    ``input_schema`` is the tool's raw JSON Schema for its parameters —
    intended to be handed to an LLM (e.g. as an OpenAI-style function
    definition) to fill in arguments. This does NOT mean the tool has been
    or will be called; ``GET /catalog/tools`` only selects candidates.
    """

    tool_id: str
    tool_name: str
    tool_description: str
    input_schema: dict[str, Any] | None
    server_id: str
    server_name: str
    score: float | None = None


class ToolSearchResponse(BaseModel):
    """Two-stage semantic search results: relevant tools within the
    caller's access-filtered, query-ranked top MCP servers."""

    results: list[ToolSearchResult]
    count: int


class PlannedToolCall(BaseModel):
    """One tool selected by the chat LLM, with its arguments filled in from
    the query. This has NOT been called against the MCP server."""

    tool_id: str
    tool_name: str
    server_id: str
    server_name: str
    arguments: dict[str, Any]
    input_schema: dict[str, Any] | None
    model: str


class ToolCallPlanResponse(BaseModel):
    """Result of ``GET /catalog/plan-tool-call``. ``plan`` is null when no
    tool call could be produced; ``message`` then explains why."""

    plan: PlannedToolCall | None
    candidates_considered: list[str]
    message: str | None = None
