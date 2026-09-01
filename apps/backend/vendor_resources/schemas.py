"""Pydantic v2 request/response contracts for the Vendor Resources API.

Covers MCP server registration, tenant grants, the access-filtered
catalog, and the AI Compiler's ``CompiledAgentSpec``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ResourceType = Literal["mcp", "datasource"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ConnectMCPServerRequest(BaseModel):
    """Payload to register a new MCP server.

    Transport, bound tools, and the required credential type are
    auto-detected by probing/connecting to the server.
    """

    name: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=4000)
    server_url: str = Field(max_length=512)
    is_global: bool = False
    # Optional credentials used *at registration time* for tool discovery on
    # auth-protected servers (not persisted).
    credentials: dict[str, str] | None = None

    @field_validator("server_url")
    @classmethod
    def _url_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("server_url must not be empty")
        return v


class McpDetectRequest(BaseModel):
    """Ask the backend to probe an MCP URL and report what it wants."""

    server_url: str = Field(min_length=1, max_length=512)


class McpCredentialField(BaseModel):
    """One credential input the UI should render for a detected auth type."""

    name: str
    label: str
    type: str = "text"
    placeholder: str = ""
    secret: bool = False
    required: bool = True


class McpDetectResponse(BaseModel):
    """Result of probing an MCP URL/command natively.

    ``auth_type`` ∈ none | api_key | bearer | basic | oauth2 | env | unknown
    ``confidence`` ∈ open | challenge | well-known | hint | command | none
    """

    ok: bool
    server_url: str
    transport: str
    endpoint: str
    reachable: bool | None = None
    auth_required: bool | None = None
    auth_type: str
    confidence: str
    credential_fields: list[McpCredentialField] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    oauth_scopes: list[str] = Field(default_factory=list)
    # Discovered OAuth metadata (RFC 8414/9728): token_endpoint,
    # registration_endpoint, scopes_supported, grant_types_supported.
    oauth: dict = Field(default_factory=dict)
    error: str | None = None


class ConnectCredentialsRequest(BaseModel):
    """Optional credentials supplied when testing/connecting to an MCP server."""

    credentials: dict[str, str] | None = None


class MCPServerResponse(BaseModel):
    """Full MCP server representation (admin view)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    transport: str
    server_url: str
    bound_tools: list
    auth_config: dict = Field(default_factory=dict)
    is_global: bool
    created_at: datetime
    updated_at: datetime


class ConnectMCPServerResponse(BaseModel):
    """Result of a connect-test: discovered transport, auth and tools."""

    model_config = ConfigDict(from_attributes=True)

    transport: str
    bound_tools: list[str]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    auth_type: str = "none"
    server_info: dict[str, Any] | None = None
    protocol_version: str | None = None


class GrantTenantResourceRequest(BaseModel):
    """Grant a Vendor Resource to a Tenant (all members inherit access)."""

    tenant_id: str = Field(min_length=1)
    resource_type: ResourceType = "mcp"
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


class AgentNode(BaseModel):
    """A single node in a compiled agent DAG (usually a bound MCP call)."""

    model_config = ConfigDict(extra="allow")

    id: str
    server_id: str | None = None
    node_type: str = "mcp.call"
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    unconfigured: bool = False


class AgentEdge(BaseModel):
    """A directed edge between two agent nodes (forms a DAG)."""

    model_config = ConfigDict(extra="allow")

    source: str
    target: str
    condition: str | None = None


class CompiledAgentSpec(BaseModel):
    """The validated, LLM-compiled agent DAG bound to MCP Server IDs."""

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