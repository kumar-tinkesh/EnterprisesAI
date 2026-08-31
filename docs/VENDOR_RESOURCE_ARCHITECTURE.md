# Technical Architecture Specification: Vendor Resources Subsystem

## 1. Executive Summary

The **Vendor Resources Subsystem** (`apps/backend/vendor_resources`) is the foundational capability catalog layer of the Enterprise AI Agent Platform. It allows **Vendor Admins** to provision and register:
1. **Tools** (REST APIs, OpenAPI Specs, Generic HTTP Connectors)
2. **MCP Servers** (Model Context Protocol via SSE and Stdio Transports)
3. **Data Sources** (RAG Knowledge Bases, Vector Indices, PDF Ingestion pipelines)

This subsystem enforces a strict **Three-Tier Access Control Model**:
* **`solo_user`**: Gains direct access to the Global Vendor Catalog for personal workspace agent creation.
* **`tenant_user`**: Inherits access to Vendor Resources granted to their Organization (`tenant_id`). All members of an authorized tenant automatically share access.

All schema contracts, input/output parameters, and AI Compiler DAG specs are validated using **Pydantic v2** (`pydantic>=2.10`), backed by `pydantic-core` in Rust for maximum speed, type safety, and structured output guarantees.

---

## 2. Root Path Mounting & Absolute Import Resolution

> **⚠️ CRITICAL RULE: No relative imports (`from ..`, `from ...`) anywhere in the codebase.**
>
> All Python imports across every module are **absolute imports from the project root**.

### How It Works

The project root (`EnterpriseAI/`) is registered as a Python path source via two mechanisms:

**1. `pyproject.toml` pythonpath (for pytest, dev tools, uv run):**

```toml
# /EnterpriseAI/pyproject.toml
[tool.pytest.ini_options]
pythonpath = [".", "apps/auth", "apps/backend", "apps/llm_gateway"]
```

**2. `sys.path` injection in entrypoints (for production / Docker / uvicorn):**

```python
# apps/backend/main.py (entrypoint)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # EnterpriseAI/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

### Import Examples Across Modules

```python
# ─── Inside apps/backend/vendor_resources/models.py ───
from src.db.base import Base, TimestampMixin          # Reuse auth Base & mixin
from src.core.roles import Roles                       # Reuse auth Roles enum

# ─── Inside apps/backend/vendor_resources/router.py ───
from src.db.session import get_db                      # Reuse auth DB session
from src.api.deps import get_current_user, require_roles  # Reuse auth JWT guards
from src.core.audit import log_audit_event             # Reuse audit logging

# ─── Inside apps/backend/vendor_resources/services/catalog_engine.py ───
from apps.llm_gateway.gateway import LLMGateway        # Reuse LLM gateway

# ─── NEVER write this ───
# from ..db import base          ❌ RELATIVE IMPORT
# from ...core import security   ❌ RELATIVE IMPORT
```

This guarantees **zero `ImportError` or `ModuleNotFoundError`** on any OS, Docker container, or production server.

---

## 3. Reusable Platform Modules (Zero Duplication)

Instead of creating duplicate utilities, `vendor_resources` reuses existing platform modules directly via absolute imports:

| Reused Module | Location | What It Provides |
|---|---|---|
| `src.db.base` | `apps/auth/src/db/base.py` | `Base` (DeclarativeBase), `TimestampMixin` (created_at/updated_at) |
| `src.db.session` | `apps/auth/src/db/session.py` | `get_db()` FastAPI dependency, `engine`, `create_db_tables()` |
| `src.core.roles` | `apps/auth/src/core/roles.py` | `Roles.VENDOR_ADMIN`, `Roles.TENANT_ADMIN`, `Roles.TENANT_USER`, `Roles.SOLO_USER` |
| `src.core.security` | `apps/auth/src/core/security.py` | `decode_token()`, `verify_password()`, `hash_password()` |
| `src.core.audit` | `apps/auth/src/core/audit.py` | `log_audit_event()` for security/admin audit trail |
| `src.api.deps` | `apps/auth/src/api/deps.py` | `get_current_user()`, `require_roles()`, `CurrentUser` model |
| `apps.llm_gateway` | `apps/llm_gateway/` | `LLMGateway` for embeddings & structured LLM outputs |

> **Result**: `vendor_resources/` contains **ONLY** its own business logic — models, schemas, services, router, vault, and tests. No duplicate DB, session, roles, or auth code.

---

## 4. Shared Database & Directory Architecture

> **Centralized Single Database**: All platform tables (`tenants`, `users`, `vendor_tools`, `vendor_mcp_servers`, `vendor_data_sources`, `tenant_resource_grants`) are stored in the **single centralized database file**:
> 👉 [`/home/AbhishekPrajapati/Desktop/EnterpriseAI/data/auth.db`](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/data/auth.db)
> `apps/backend/vendor_resources` contains **ONLY application code** operating on this shared database.

> **Global Dependency Management**: All Python dependencies across the entire platform (including `apps/auth`, `apps/backend`, `apps/llm_gateway`, and `scripts/`) are managed globally in the **single root file** [`/home/AbhishekPrajapati/Desktop/EnterpriseAI/pyproject.toml`](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/pyproject.toml).

> **Directory Rule**: There is **no `src/` directory** inside `apps/backend/`. `main.py` and `config.py` reside at the top level of `apps/backend/` as overall backend service entrypoints. There is **no `db/` directory** inside `vendor_resources/` — database Base, session, and engine are reused from `apps/auth/src/db/`.

```text
EnterpriseAI/                             # Repository Root (registered in sys.path)
├── pyproject.toml                         # 🌟 SINGLE GLOBAL DEPENDENCY MANIFEST FOR ENTIRE APP
├── uv.lock                                # Single lockfile for all Python services
│
├── data/
│   └── auth.db                            # 🗄️ SINGLE CENTRAL DATABASE FOR ALL TABLES & DATA
│
├── apps/
│   ├── auth/                              # ♻️ REUSED: DB Base, Session, Roles, Security, Audit, Deps
│   │   └── src/
│   │       ├── db/
│   │       │   ├── base.py                # Base, TimestampMixin  ← REUSED by vendor_resources
│   │       │   └── session.py             # get_db(), engine       ← REUSED by vendor_resources
│   │       ├── core/
│   │       │   ├── roles.py               # Roles enum             ← REUSED by vendor_resources
│   │       │   ├── security.py            # JWT decode/verify      ← REUSED by vendor_resources
│   │       │   └── audit.py               # log_audit_event()      ← REUSED by vendor_resources
│   │       └── api/
│   │           └── deps.py                # get_current_user(), require_roles() ← REUSED
│   │
│   ├── llm_gateway/                       # ♻️ REUSED: LLM embeddings & structured outputs
│   │   └── gateway.py                     # LLMGateway             ← REUSED by catalog_engine
│   │
│   └── backend/                           # Backend Application Directory
│       ├── __init__.py
│       ├── main.py                        # FastAPI entrypoint (sys.path root injection + router mount)
│       ├── config.py                      # 12-factor config (DATABASE_URL, JWT keys, Vault secrets)
│       │
│       └── vendor_resources/              # 🚀 NEW: ALL VENDOR RESOURCE BUSINESS LOGIC
│           ├── __init__.py                # Package exports
│           ├── router.py                  # FastAPI REST Endpoints (Tools, MCP, Data Sources, Catalog)
│           ├── schemas.py                 # Pydantic v2 Contracts (Tool, MCP, Data Source Specs)
│           ├── models.py                  # SQLAlchemy 2.0 ORM Models (inherits from src.db.base.Base)
│           │
│           ├── core/                      # Vendor-Specific Security & Encryption
│           │   ├── __init__.py
│           │   └── vault.py               # AES-256 / HashiCorp Vault Secret Encryption Driver
│           │
│           ├── services/                  # Business Logic Drivers
│           │   ├── __init__.py
│           │   ├── tool_service.py        # OpenAPI Ingestion & REST API Connector Engine
│           │   ├── mcp_service.py         # MCP Handshake & Tool Auto-Discovery (SSE/Stdio)
│           │   ├── datasource_service.py  # Document Parsing, Chunking & pgvector Indexer
│           │   └── catalog_engine.py      # Semantic Search & Context Shrinker for AI Compiler
│           │
│           ├── seed/                      # Default System Seed Resources
│           │   ├── default_tools.py       # Pre-built system tools (HTTP Request, Email, Slack)
│           │   └── default_rag.py         # Default knowledge base templates
│           │
│           └── tests/                     # 🧪 ALL VENDOR RESOURCE TESTS INSIDE MODULE
│               ├── __init__.py
│               ├── conftest.py            # Shared fixtures (test DB, mock users, auth headers)
│               ├── test_router.py         # REST Endpoint Tests (Tools, MCP, Data Sources, Catalog)
│               └── test_services.py       # Service & Catalog Engine Integration Tests
```

---

## 5. Database Schema Design (SQLAlchemy 2.0)

Defined in `apps/backend/vendor_resources/models.py`. All models inherit from the shared `Base` and `TimestampMixin` via absolute import:

```python
from src.db.base import Base, TimestampMixin   # ← Absolute import, reused from auth
```

### `vendor_tools` Table
Stores declarative REST API definitions and JSON parameter schemas.

```python
class VendorTool(Base, TimestampMixin):
    __tablename__ = "vendor_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True) # finance, hr, support
    method: Mapped[str] = mapped_column(String(16), default="POST")
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=True)
    parameters_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    vault_secret_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

### `vendor_mcp_servers` Table
Stores registered MCP Servers and auto-discovered capability tool lists.

```python
class VendorMCPServer(Base, TimestampMixin):
    __tablename__ = "vendor_mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), default="sse") # sse | stdio
    server_url: Mapped[str] = mapped_column(String(512), nullable=False)
    bound_tools: Mapped[list] = mapped_column(JSONB, default=list) # List of tool names
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
```

### `vendor_data_sources` Table
Stores Knowledge Base (RAG) indices and embedding settings.

```python
class VendorDataSource(Base, TimestampMixin):
    __tablename__ = "vendor_data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), default="vector_db") # pdf_collection, vector_db
    vector_index_name: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), default="text-embedding-3-small")
    chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
```

### `tenant_resource_grants` Table
Maps which Vendor Resources are enabled for specific Tenants.

```python
class TenantResourceGrant(Base, TimestampMixin):
    __tablename__ = "tenant_resource_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(32)) # tool | mcp | datasource
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
```

---

## 6. Pydantic v2 Data Models (`vendor_resources/schemas.py`)

```python
from typing import Literal, Any, Optional
from pydantic import BaseModel, Field, HttpUrl

class CreateVendorToolRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str = Field(min_length=5, description="Used by AI Compiler for LLM selection")
    category: Literal["finance", "hr", "support", "sales", "custom"]
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    endpoint_url: Optional[str] = None
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    is_global: bool = False

class ConnectMCPServerRequest(BaseModel):
    name: str
    transport: Literal["sse", "stdio"] = "sse"
    server_url: str
    is_global: bool = False

class CreateDataSourceRequest(BaseModel):
    name: str
    type: Literal["pdf_collection", "vector_db", "sql_database"] = "vector_db"
    vector_index_name: str
    embedding_model: str = "text-embedding-3-small"
    is_global: bool = False

class GrantTenantResourceRequest(BaseModel):
    tenant_id: str
    resource_type: Literal["tool", "mcp", "datasource"]
    resource_id: str

class CompiledAgentSpec(BaseModel):
    agent_name: str
    description: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
```

---

## 7. Security & Access Control Architecture

Authorization reuses `src.api.deps.get_current_user` and `src.api.deps.require_roles` directly. No duplicate auth code:

```python
# vendor_resources/router.py — reuse auth guards via absolute imports
from src.api.deps import get_current_user, require_roles, CurrentUser
from src.core.roles import Roles

# Vendor-only endpoint
@router.post("/tools", dependencies=[Depends(require_roles(Roles.VENDOR_ADMIN))])
async def create_tool(...): ...

# User-facing catalog (solo_user + tenant_user)
@router.get("/catalog")
async def get_catalog(user: CurrentUser = Depends(get_current_user)): ...
```

### Access Control Flow

```
                               ┌────────────────────────────────┐
                               │     GLOBAL VENDOR CATALOG      │
                               └───────────────┬────────────────┘
                                               │
             ┌─────────────────────────────────┴─────────────────────────────────┐
             │                                                                   │
             ▼                                                                   ▼
 ┌───────────────────────┐                                           ┌───────────────────────┐
 │       SOLO USER       │                                           │  TENANT ORGANIZATION  │
 │ (Direct Platform Acc.)│                                           │(Tenant Resource Grant)│
 └───────────┬───────────┘                                           └───────────┬───────────┘
             │ Direct Access                                                     │ Inherited Access
             ▼                                                                   ▼
 ┌───────────────────────┐                                           ┌───────────────────────┐
 │ Solo Personal Agents  │                                           │ ALL Tenant Members    │
 └───────────────────────┘                                           │ (Admin & Users)       │
                                                                     └───────────────────────┘
```

### Authorization Query Logic (`services/catalog_engine.py`)

When retrieving authorized capabilities for a user creating an agent from `./data/auth.db`:

```python
from src.db.session import get_db                         # ← Reused
from src.api.deps import CurrentUser                       # ← Reused
from apps.backend.vendor_resources.models import (         # ← Absolute import
    VendorTool, VendorMCPServer, VendorDataSource, TenantResourceGrant
)

async def get_authorized_vendor_catalog(db: AsyncSession, user: CurrentUser) -> dict:
    """Fetch authorized Vendor Tools, MCPs, and Data Sources based on user role and tenant_id."""

    if user.role == "solo_user":
        # Solo users get direct access to all Global Vendor Resources
        tools = await db.execute(select(VendorTool).where(VendorTool.is_global.is_(True)))
        mcps = await db.execute(select(VendorMCPServer).where(VendorMCPServer.is_global.is_(True)))
        datasources = await db.execute(select(VendorDataSource).where(VendorDataSource.is_global.is_(True)))
    else:
        # Tenant users inherit access granted to their organization
        granted_resource_ids = (
            await db.execute(select(TenantResourceGrant.resource_id).where(TenantResourceGrant.tenant_id == user.tenant_id))
        ).scalars().all()

        tools = await db.execute(select(VendorTool).where(VendorTool.id.in_(granted_resource_ids)))
        mcps = await db.execute(select(VendorMCPServer).where(VendorMCPServer.id.in_(granted_resource_ids)))
        datasources = await db.execute(select(VendorDataSource).where(VendorDataSource.id.in_(granted_resource_ids)))

    return {
        "tools": tools.scalars().all(),
        "mcp_servers": mcps.scalars().all(),
        "data_sources": datasources.scalars().all(),
    }
```

---

## 8. AI Compiler Integration Engine

When a user submits a Natural Language prompt (e.g. *"Verify vendor invoice > $5,000 against CFO Policy PDF"*):

```
[User NL Request] ──> [Catalog Filter (Solo/Tenant)] ──> [Semantic Tool Matcher] ──> [LLM Compiler] ──> [LangGraph Spec]
```

1. **Access Filtering**: Pulls authorized catalog for the `solo_user` or `tenant_user`.
2. **Semantic Matching**: Embeds user query and runs similarity search against tool descriptions to pick Top-5 relevant tools.
3. **JSON Schema Shrinking**: Removes verbose comments/descriptions from schemas to save LLM tokens.
4. **Structured Spec Generation**: Passes compressed context to LLM requesting structured Pydantic v2 `CompiledAgentSpec` output.

The catalog engine uses `apps.llm_gateway.gateway.LLMGateway` (reused via absolute import) for embedding generation and structured LLM outputs.

---

## 9. FastAPI REST Routes (`vendor_resources/router.py`)

All routes reuse `get_current_user`, `require_roles`, and `get_db` from `src.api.deps` and `src.db.session`:

| Method | Endpoint | Access Role | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/vendor/resources/tools` | `vendor_admin` | Ingest OpenAPI Spec or REST Tool |
| `POST` | `/api/v1/vendor/resources/mcp` | `vendor_admin` | Connect MCP Server (SSE/Stdio) |
| `POST` | `/api/v1/vendor/resources/datasources` | `vendor_admin` | Upload & Index Knowledge Base |
| `GET` | `/api/v1/vendor/resources/catalog` | `solo_user`, `tenant_user` | Fetch authorized catalog for AI Compiler |
| `POST` | `/api/v1/vendor/resources/grants` | `vendor_admin` | Grant Vendor Resource to a Tenant ID |
| `DELETE` | `/api/v1/vendor/resources/{id}` | `vendor_admin` | Delete or revoke Vendor Resource |

---

## 10. Step-by-Step Flow: Adding Vendor Resources & Usage by Tenants/Users

```
===========================================================================================================
PHASE 1: STEP-BY-STEP VENDOR RESOURCE PROVISIONING & REGISTRATION
===========================================================================================================

 [Vendor Admin Dashboard / API]
  Select Resource Type: REST API / OpenAPI | MCP Server | Data Source (RAG)
            │
            ├──► Case 1: REST Tool  ──► Ingest OpenAPI JSON ──► Generate Pydantic Schema ──► Store Keys in Vault
            ├──► Case 2: MCP Server ──► Connect SSE/Stdio   ──► Send mcp.initialize()   ──► Discover Tools (list_tools)
            └──► Case 3: RAG Source ──► Extract PDF Text    ──► Chunk (512 tokens)      ──► Embed Vectors in pgvector
            │
            ▼
 [Catalog Database & Vector Indexing]
  • Save Resource Record to Database (`vendor_tools`, `vendor_mcp_servers`, or `vendor_data_sources` in `./data/auth.db`)
  • Embed Resource Name & Description into `tool_vector_store` for AI Compiler Matcher
  • Mark Resource Scope: `is_global = True` (For Solo Users) OR `is_global = False` (Requires Tenant Grant)


===========================================================================================================
PHASE 2: TENANT ACCESS GRANTING (For Tenant Users)
===========================================================================================================

 [Vendor Admin Dashboard / API]
  Call: POST /api/v1/vendor/resources/grants
  Payload: { "tenant_id": "tenant_enterprise_01", "resource_id": "tool_stripe_invoices" }
            │
            ▼
 [Record Written to `tenant_resource_grants`]
  Tenant "tenant_enterprise_01" is now granted access to "tool_stripe_invoices".
  ALL members under "tenant_enterprise_01" (Tenant Admin, Tenant User 1, Tenant User 2) instantly inherit access!


===========================================================================================================
PHASE 3: USAGE BY TENANT USER & SOLO USER (NL Agent Creation & Execution)
===========================================================================================================

 [Tenant User OR Solo User]
  Types NL Query on Canvas: "Verify invoice > $5,000 against CFO Policy PDF and send alert on Slack"
            │
            ▼
 [Registry Catalog Engine Filter]
  • If `solo_user`   ──► Pull ALL Global Vendor Resources (`is_global = True`)
  • If `tenant_user` ──► Pull ALL Vendor Resources granted to user's `tenant_id`
            │
            ▼
 [Semantic Tool Matcher]
  Performs similarity search between User NL Query vector and Filtered Resource Vector Index (Returns Top-5 Items)
            │
            ▼
 [AI Compiler & LangGraph Execution]
  Compiles validated Pydantic v2 `AgentSpec` DAG bound to exact Vendor Tool IDs and executes via LangGraph engine!
```

---

## 11. Import Dependency Map

Visual map of how `vendor_resources` imports flow — all absolute, no relative:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        EnterpriseAI/ (Root in sys.path)                     │
│                                                                              │
│  ┌─────────────────────┐      ┌──────────────────────┐                      │
│  │   apps/auth/src/    │      │  apps/llm_gateway/   │                      │
│  │  ┌───────────┐      │      │  ┌────────────────┐  │                      │
│  │  │ db/base   │◄─────┼──────┼──┤                │  │                      │
│  │  │ db/session│◄─────┼──┐   │  │    gateway.py  │◄─┼──────────────┐      │
│  │  │ core/roles│◄─────┼──┤   │  └────────────────┘  │              │      │
│  │  │ core/audit│◄─────┼──┤   └──────────────────────┘              │      │
│  │  │ core/sec  │◄─────┼──┤                                         │      │
│  │  │ api/deps  │◄─────┼──┤                                         │      │
│  │  └───────────┘      │  │                                         │      │
│  └─────────────────────┘  │                                         │      │
│                            │   ┌────────────────────────────────────┐│      │
│                            │   │  apps/backend/vendor_resources/   ││      │
│                            │   │                                    ││      │
│                            ├───┤  models.py     (uses Base, Mixin)  ││      │
│                            ├───┤  router.py     (uses deps, roles)  ││      │
│                            ├───┤  services/     (uses audit, deps)  ││      │
│                            └───┤  catalog_engine (uses LLMGateway)──┘│      │
│                                │  core/vault.py (standalone AES)    │      │
│                                │  schemas.py    (standalone Pydantic)│      │
│                                └────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────────────┘

All arrows = absolute imports (e.g. from src.db.base import Base)
Zero relative imports in the entire codebase ✓
```
