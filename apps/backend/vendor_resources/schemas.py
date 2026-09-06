"""Pydantic v2 request/response contracts for the Vendor Resources API.

Covers MCP server registration, tenant grants, the access-filtered
catalog, and the AI Compiler's ``CompiledAgentSpec``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ResourceType = Literal["mcp", "datasource"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class AnalyzeRepoRequest(BaseModel):
    """Request to analyze a GitHub repository or other URL for MCP characteristics."""

    repo_url: str = Field(
        min_length=1,
        max_length=512,
        description="GitHub repository URL (e.g., https://github.com/org/repo) or direct MCP endpoint URL",
    )


class AnalyzeRepoResponse(BaseModel):
    """Analysis result of an MCP server repository or endpoint.

    Contains detected transport type, runtime, command suggestion, remote endpoint,
    required environment variables, and authentication type.
    """

    detected: bool = Field(..., description="Whether analysis was successful")
    transport: str = Field(
        ...,
        description="Detected transport: stdio, streamable_http, sse, docker, unknown",
    )
    runtime: str = Field(..., description="Runtime environment: node, python, docker, go, rust, remote, custom, unknown")
    suggested_command: str | None = Field(None, description="Suggested command to start the MCP server")
    remote_endpoint: str | None = Field(None, description="Remote MCP endpoint URL if detected")
    required_env_vars: list[str] = Field(default_factory=list, description="Environment variable names required by the MCP server")
    auth_type: str = Field(..., description="Authentication type: none, api_key, bearer, basic, oauth2, env, unknown")
    hints: list[str] = Field(default_factory=list, description="Analysis hints and warnings")


class AddMCPServerRequest(BaseModel):
    """Unified request to add an MCP server from either a Remote MCP URL or a GitHub/Source repository URL.

    Step 1: Register only — analyzes source, detects transport/runtime/auth,
    saves normalized config. Does NOT attempt connection if credentials are missing.
    """

    name: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=4000)
    # source_url is the primary field, but we accept server_url and source_repo_url as fallbacks
    source_url: str | None = Field(default=None, max_length=512, description="Remote MCP endpoint URL (https://...) OR GitHub/source repo URL")
    # Accept server_url as alias for backward compatibility with old frontend
    server_url: str | None = Field(None, max_length=512)
    # Source repository URL (GitHub) - used when server_url is a command not a URL
    source_repo_url: str | None = Field(None, max_length=512)
    is_global: bool = False
    # Optional: override detected source_type ('github' | 'remote' | 'local')
    source_type: str | None = Field(None, pattern="^(github|remote|local)$")
    # Optional: for GitHub monorepos, subpath to the MCP server (e.g. 'src/filesystem')
    source_subpath: str | None = Field(None, max_length=512)
    # Optional: branch/tag for GitHub repos
    source_branch: str | None = Field(default="main", max_length=255)

    @model_validator(mode="before")
    @classmethod
    def _resolve_source_url(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # 1. Extract raw value from source_url, server_url, or source_repo_url
        v = data.get("source_url") or data.get("server_url")
        if not v and data.get("source_repo_url"):
            v = data.get("source_repo_url")

        # 2. If v is a dict or object (e.g. {"url": "..."}, extract url property if present)
        if isinstance(v, dict):
            v = v.get("url") or v.get("source_url") or v.get("href")

        # Clean up dict values if sent in server_url or source_repo_url or source_url
        if isinstance(data.get("source_url"), dict):
            data["source_url"] = str(v) if v else None
        if isinstance(data.get("server_url"), dict):
            data["server_url"] = str(v) if v else None
        if isinstance(data.get("source_repo_url"), dict):
            data["source_repo_url"] = str(v) if v else None

        # 3. If v is not a URL (e.g., npx command in server_url), check source_repo_url
        if v and isinstance(v, str) and not (v.startswith("http://") or v.startswith("https://")):
            repo = data.get("source_repo_url")
            if repo and isinstance(repo, str):
                v = repo

        if v is not None:
            data["source_url"] = str(v).strip()

        return data

    @field_validator("source_url", mode="after")
    @classmethod
    def _require_source_url(cls, v: str | None) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError("Either source_url, server_url, or source_repo_url must be provided as a valid non-empty string URL")
        return v.strip()


class ConnectMCPServerRequest(BaseModel):
    """Payload to register a new MCP server (legacy — kept for backward compat).

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
    # Source repository URL (GitHub) that this MCP server originated from
    source_repo_url: str | None = Field(None, max_length=512, description="GitHub repository URL that contains this MCP server")
    # Environment variables required by the MCP server (detected from repo analysis)
    env_vars: dict[str, str] | None = Field(None, description="Environment variables required by the MCP server")

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


class OAuthConfigRequest(BaseModel):
    """Manually supply a server's OAuth endpoints.

    Needed when they can't be auto-discovered — e.g. a local stdio server
    isn't running yet at analysis time, so there's nothing to probe via
    RFC 8414. Most providers publish these as fixed, documented URLs
    (Intuit's, Slack's, …), so this is a one-time admin paste, not
    per-vendor code.
    """

    authorization_endpoint: str
    token_endpoint: str
    scope: str | None = None
    extra_authorize_params: dict[str, str] | None = None


class OAuthAuthorizeRequest(BaseModel):
    """Start a 'Connect via OAuth' bootstrap for a server."""

    client_id: str
    client_secret: str
    scope: str | None = None


class OAuthAuthorizeResponse(BaseModel):
    """Where to send the admin's browser to complete the provider's consent
    screen, and the state token that flow will round-trip back."""

    authorization_url: str
    state: str


class MCPServerResponse(BaseModel):
    """Full MCP server representation (admin view)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    status: str
    transport: str
    server_url: str
    bound_tools: list
    auth_config: dict = Field(default_factory=dict)
    is_global: bool
    source_repo_url: str | None = None
    env_vars: dict | None = None
    created_at: datetime
    updated_at: datetime
    # New normalized config fields (Section 19)
    source_type: str | None = None
    source_repo: str | None = None
    source_branch: str | None = None
    source_subpath: str | None = None
    transport_type: str | None = None
    transport_confidence: float | None = None
    transport_evidence: list[dict] | None = None
    runtime_type: str | None = None
    command: str | None = None
    args: list[str] | None = None
    working_directory: str | None = None
    endpoint: str | None = None
    auth_type: str | None = None
    auth_schema: dict | None = None


class AddMCPServerResponse(BaseModel):
    """Result of Step 1: server registered with normalized config, status=UNCONNECTED."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    status: str = "UNCONNECTED"
    is_global: bool = False
    source_type: str | None = None
    transport_type: str | None = None
    transport_confidence: float | None = None
    transport_evidence: list[dict] | None = None
    runtime_type: str | None = None
    command: str | None = None
    args: list[str] | None = None
    working_directory: str | None = None
    endpoint: str | None = None
    auth_type: str | None = None
    auth_schema: dict | None = None
    created_at: datetime
    updated_at: datetime


class ConnectMCPServerResponse(BaseModel):
    """Result of Step 2: test connection and discover tools."""

    model_config = ConfigDict(from_attributes=True)

    transport: str
    bound_tools: list[str]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    auth_type: str = "none"
    server_info: dict[str, Any] | None = None
    protocol_version: str | None = None
    status: str = "VERIFIED"


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