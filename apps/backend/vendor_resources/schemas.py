"""Pydantic v2 request/response contracts for the Vendor Resources API.

Covers Vendor Tools, tenant grants, the access-filtered catalog, and the AI
Compiler's ``CompiledAgentSpec`` (Phase 3). MCP server and data-source schemas
remain deferred.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Resource types currently supported by the grant table. ``mcp_server`` and
# ``data_source`` are reserved for later phases.
ResourceType = Literal["vendor_tool", "mcp_server", "data_source"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class CreateVendorToolRequest(BaseModel):
    """Payload to register a new Vendor Tool."""

    name: str = Field(min_length=2, max_length=128)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="general", max_length=64)
    method: HttpMethod = "POST"
    endpoint_url: str | None = Field(default=None, max_length=512)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    is_global: bool = False
    vault_secret_ref: str | None = Field(default=None, max_length=255)

    @field_validator("parameters_schema")
    @classmethod
    def _must_be_dict(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("parameters_schema must be a JSON object")
        return v


class VendorToolResponse(BaseModel):
    """Full tool representation (admin view)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    category: str
    method: str
    endpoint_url: str | None
    parameters_schema: dict[str, Any]
    is_global: bool
    vault_secret_ref: str | None
    created_at: datetime
    updated_at: datetime


class GrantTenantResourceRequest(BaseModel):
    """Grant a Vendor Resource to a Tenant (all members inherit access)."""

    tenant_id: str = Field(min_length=1)
    resource_type: ResourceType = "vendor_tool"
    resource_id: str = Field(min_length=1)


class GrantResponse(BaseModel):
    """A granted resource ↔ tenant mapping."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    created_at: datetime


class CatalogEntry(BaseModel):
    """A catalog tool as seen by a consumer (never exposes secret refs)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    category: str
    method: str
    endpoint_url: str | None
    parameters_schema: dict[str, Any]


class CatalogResponse(BaseModel):
    """The authorized catalog for the calling user (access-filtered)."""

    tools: list[CatalogEntry]
    count: int


# ── AI Compiler (Phase 3) ────────────────────────────────────────────────────


class AgentNode(BaseModel):
    """A single node in a compiled agent DAG (usually a bound Vendor Tool call)."""

    model_config = ConfigDict(extra="allow")  # tolerate extra LLM-emitted keys

    id: str
    tool_id: str | None = None
    node_type: str = "tool.call"  # tool.call | logic.condition | notification.send | ai.agent
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    unconfigured: bool = False  # True when no matching tool / no endpoint


class AgentEdge(BaseModel):
    """A directed edge between two agent nodes (forms a DAG)."""

    model_config = ConfigDict(extra="allow")

    source: str  # avoid the `from` keyword
    target: str
    condition: str | None = None  # optional, for logic.condition branches


class CompiledAgentSpec(BaseModel):
    """The validated, LLM-compiled agent DAG bound to Vendor Tool IDs."""

    agent_name: str
    description: str = ""
    nodes: list[AgentNode] = Field(default_factory=list)
    edges: list[AgentEdge] = Field(default_factory=list)


class CompileAgentRequest(BaseModel):
    """Compile a natural-language request into a ``CompiledAgentSpec``."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class RunAgentRequest(BaseModel):
    """Compile and execute a natural-language request."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class RunAgentResponse(BaseModel):
    """Result of compile + execute: the spec plus per-node results."""

    spec: CompiledAgentSpec
    results: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)