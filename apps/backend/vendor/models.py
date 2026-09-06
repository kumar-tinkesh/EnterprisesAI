"""SQLAlchemy 2.0 ORM models for the Vendor Resources subsystem.

All models inherit the shared :class:`~src.db.base.Base` and
:class:`~src.db.base.TimestampMixin` (reused from the Auth service via absolute
imports), so they attach to the *same* ``Base.metadata`` as the auth tables and
live in the single centralized database.

Architecture doc §24 — Universal MCP Server Flow
=================================================
``VendorMCPServer`` is the central registry entry for any MCP server regardless
of how it was discovered or how it is launched:

  * **source_type** ``'github'`` — server lives in a GitHub repo; resolved from
    ``source_repo`` / ``source_branch`` / ``source_subpath``.
  * **source_type** ``'remote'`` — already-hosted HTTP/SSE endpoint; the
    ``endpoint`` column holds the URL.
  * **source_type** ``'local'`` — binary or directory on the filesystem.

Transport negotiation stores a **confidence score** and **evidence chain** so
the UI can show *why* a transport was chosen rather than just the raw value.

Backward-compat columns (``server_url``, ``source_repo_url``, ``auth_config``,
``env_vars``, ``bound_tools``) are preserved; all new code should use the typed
replacements.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin


def uuid_str() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# VendorMCPServer
# ---------------------------------------------------------------------------

class VendorMCPServer(Base, TimestampMixin):
    """Registry entry for a single MCP Server (any transport, any source).

    Lifecycle
    ---------
    ``status`` starts as ``'UNCONNECTED'`` and transitions to ``'VERIFIED'``
    once the detection pipeline successfully introspects the server (tools list
    retrieved, transport confirmed, auth schema resolved).

    Source columns
    --------------
    One of three paths is used, captured by ``source_type``:

    * ``'github'``  → ``source_repo``, ``source_branch``, ``source_subpath``
    * ``'remote'``  → ``endpoint``
    * ``'local'``   → ``command``, ``args``, ``working_directory``

    Transport columns
    -----------------
    ``transport`` holds the canonical value (``'sse'``, ``'stdio'``, …).
    ``transport_confidence`` (0.0–1.0) and ``transport_evidence``
    (list of ``{source, reason}`` dicts) record how it was determined.

    Auth columns
    ------------
    ``auth_type`` is the normalized auth mechanism (``'none'``, ``'api_key'``,
    ``'bearer'``, ``'basic'``, ``'oauth2'``, ``'env'``).
    ``auth_schema`` describes the fields the UI must collect:
    ``{"fields": [{"name": …, "label": …, "type": …, "required": bool,
                   "secret": bool, "location": "header"|"query"|"env"}]}``.
    ``auth_config`` is kept for backward compatibility with older code.
    """

    __tablename__ = "vendor_mcp_servers"

    # ------------------------------------------------------------------
    # Primary identity
    # ------------------------------------------------------------------
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_global: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )

    # ------------------------------------------------------------------
    # Lifecycle status  (UNCONNECTED | VERIFIED)
    # ------------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNCONNECTED", index=True
    )

    # ------------------------------------------------------------------
    # Ownership  (vendor | tenant)
    # ------------------------------------------------------------------
    ownership_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ------------------------------------------------------------------
    # Source — how the server is obtained / where it lives
    # source_type: 'github' | 'remote' | 'local'
    # ------------------------------------------------------------------
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)

    # GitHub source fields
    source_repo: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
        comment="GitHub repo in 'owner/repo' format, e.g. 'anthropics/mcp-filesystem'"
    )
    source_branch: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Branch/tag to check out, e.g. 'main'"
    )
    source_subpath: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
        comment="Path inside the repo to the server root, e.g. 'src/filesystem'"
    )

    # Legacy — kept for backward compatibility; prefer source_* columns above
    source_repo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Remote/HTTP source field (also used as the runtime endpoint for HTTP/SSE)
    server_url: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
        comment="Legacy server URL; prefer 'endpoint' for new code"
    )

    # ------------------------------------------------------------------
    # Transport detection
    # transport: 'sse' | 'stdio' | 'http' | 'websocket' | …
    # ------------------------------------------------------------------
    transport: Mapped[str] = mapped_column(
        String(32), nullable=False, default="sse",
        comment="Canonical transport type (sse, stdio, http, …)"
    )
    transport_confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Detection confidence score, 0.0–1.0"
    )
    transport_evidence: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True,
        comment="List of {source, reason} dicts explaining transport choice"
    )

    # ------------------------------------------------------------------
    # Runtime — how the server process is launched (stdio / local)
    # runtime_type: 'node' | 'python' | 'go' | 'rust' | 'docker' |
    #               'binary' | 'unknown'
    # ------------------------------------------------------------------
    runtime_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    command: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True,
        comment="Startup command, e.g. 'node', 'python', 'npx'"
    )
    args: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True,
        comment="Command-line arguments as a list of strings"
    )
    working_directory: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True,
        comment="Working directory for process launch"
    )

    # ------------------------------------------------------------------
    # Network endpoint (remote / SSE / HTTP transport)
    # ------------------------------------------------------------------
    endpoint: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
        comment="HTTP/SSE endpoint URL for remote transport"
    )

    # ------------------------------------------------------------------
    # Auth
    # auth_type: 'none' | 'api_key' | 'bearer' | 'basic' | 'oauth2' | 'env'
    # ------------------------------------------------------------------
    auth_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="Normalized auth mechanism"
    )
    auth_schema: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment=(
            "Credential field schema: "
            '{"fields": [{"name", "label", "type", "required", "secret", "location"}]}'
        ),
    )

    # Legacy auth blob — kept for backward compatibility
    auth_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ------------------------------------------------------------------
    # Env / tool binding — legacy, kept for backward compatibility
    # ------------------------------------------------------------------
    env_vars: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    bound_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # ------------------------------------------------------------------
    # Semantic search — embedding of "name. description" for catalog
    # matching (see user.services.catalog_engine). ``dim`` and
    # ``embedding_model`` let callers detect a stale/mismatched vector (e.g.
    # after switching embedding providers) instead of comparing garbage.
    # ------------------------------------------------------------------
    embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    dim: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)


# ---------------------------------------------------------------------------
# VendorMCPCredential  (unchanged)
# ---------------------------------------------------------------------------

class VendorMCPCredential(Base, TimestampMixin):
    """Encrypted credentials for an MCP server (vendor-level, per-tenant, or
    per-user).

    ``encrypted_credentials`` holds a Fernet-encrypted JSON blob of the
    credential fields (API keys, basic passwords, OAuth client secrets and
    refresh tokens).

    Two distinct row "kinds" share this table, distinguished by ``user_id``:

    * ``user_id IS NULL`` — a shared row (vendor-level when ``tenant_id`` is
      also ``NULL``, or a tenant-wide fallback otherwise). This is the only
      kind that existed before per-user isolation; ``ix_vmc_server_tenant_shared``
      keeps it unique per ``(server_id, tenant_id)``, unchanged.
    * ``user_id IS NOT NULL`` — a single end user's own credential for a
      server, isolated from every other user (even within the same tenant).
      ``ix_vmc_server_user`` keeps it unique per ``(server_id, user_id)``.

    Managed by ``vendor.services.mcp_auth``.
    """

    __tablename__ = "vendor_mcp_credentials"
    __table_args__ = (
        Index(
            "ix_vmc_server_tenant_shared",
            "server_id",
            "tenant_id",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
            sqlite_where=text("user_id IS NULL"),
        ),
        Index(
            "ix_vmc_server_user",
            "server_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    server_id: Mapped[str] = mapped_column(
        ForeignKey("vendor_mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)


# ---------------------------------------------------------------------------
# TenantResourceGrant  (unchanged)
# ---------------------------------------------------------------------------

class TenantResourceGrant(Base, TimestampMixin):
    """Maps a Vendor Resource (mcp / datasource) to a Tenant.

    All members of the granted tenant inherit access automatically.
    The ``resource_type`` string already accommodates ``datasource`` values
    added in later phases without a schema change.
    """

    __tablename__ = "tenant_resource_grants"
    __table_args__ = (
        Index(
            "ix_grant_tenant_resource",
            "tenant_id",
            "resource_type",
            "resource_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)


# ---------------------------------------------------------------------------
# MCPTool  (new — §24)
# ---------------------------------------------------------------------------

class MCPTool(Base, TimestampMixin):
    """A single tool advertised by an MCP server.

    Populated during the detection / verification phase when the server's
    ``tools/list`` endpoint is called. Each row corresponds to one tool entry
    in the MCP protocol response.

    ``input_schema`` and ``output_schema`` store the raw JSON Schema objects
    from the protocol (``{"type": "object", "properties": {…}}``). They are
    ``NULL`` when the server has not yet been contacted or the tool list has
    not been resolved.
    """

    __tablename__ = "vendor_mcp_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    mcp_server_id: Mapped[str] = mapped_column(
        ForeignKey("vendor_mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Semantic search — embedding of "name. description" (+ input_schema
    # property names) for tool-level catalog matching. See VendorMCPServer
    # above for why ``dim``/``embedding_model`` are tracked alongside it.
    embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    dim: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
