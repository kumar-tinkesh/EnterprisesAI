# EnterpriseAI — Architecture & Component Authentication Flows

This document provides a comprehensive technical overview of the **EnterpriseAI Platform Architecture**, detailing the **Flow of Each Component**, the **3-Tier Multi-Tenant Security Hierarchy**, the **End-to-End Authentication & Execution Model**, and the **Role Interaction & Universal MCP Server Lifecycle Guide**.

> Last updated: 2026-09-03 — reflects the current `main-llmgatway-vendor` deployment (5 containers + optional Postgres), the Universal MCP Engine (GitHub repo analysis → isolated stdio/remote execution), and the stdio process-isolation hardening (`uv run --directory`, env sanitization, repo-cache reuse).

---

## 1. System Overview & Component Topology

EnterpriseAI is structured into microservices with centralized shared database access and standardized authentication token contracts (RS256 JWT issued by `auth`, verified by every other service). All HTTP services are FastAPI except the Next.js frontend:

```text
 ┌───────────────────────────────────────────────────────────────────────────────────────────┐
 │                            ENTERPRISEAI PLATFORM — RUNTIME TOPOLOGY                       │
 │                                                                                           │
 │                        ┌──────────────────────────────────────────┐                       │
 │                        │              BROWSER (Operator)          │                       │
 │                        │        Next.js 15 UI   web :3000         │                       │
 │                        └───────┬──────────────────────────┬───────┘                       │
 │                                │ Bearer JWT               │ Bearer JWT                    │
 │               ┌────────────────┴─────────┐  ┌──────────────┴────────────────┐             │
 │               ▼                          │  ▼                               │             │
 │  ┌─────────────────────┐                │  ┌────────────────────────────┐  │             │
 │  │ AUTH SERVICE        │                │  │ BACKEND SERVICE            │  │             │
 │  │ apps/auth   :8001   │                │  │ apps/backend       :8002   │  │             │
 │  │ · login/refresh/JWKS│                │  │ · /vendor/resources/mcp/*  │  │             │
 │  │ · tenants, users    │                │  │ · catalog / grants / vault │  │             │
 │  │ · SSO (Google OIDC) │                │  │ · Universal MCP Engine ────┼──┼──┐          │
 │  │ · audit events      │                │  └────────────────────────────┘  │  │          │
 │  └──────────┬──────────┘                │                                  │  │          │
 │             │     SQLAlchemy (async)    │                                  │  │          │
 │             ▼                           ▼                                  │  ▼          │
 │  ┌──────────────────────────────────────────────┐      MCP stdio subprocess │  ┌───────┐│
 │  │ CENTRAL DATABASE                             │      (per server, own venv)│  │ REDIS ││
 │  │ data/auth.db  SQLite (default)               │                            │  │ :6379 ││
 │  │ or  db :5432  Postgres 16 (DATABASE_URL opt) │                            │  └───────┘│
 │  │ tenants · users · workspaces · grants        │                            │           │
 │  │ vendor_tools · vendor_mcp_servers · audit    │                            │           │
 │  └──────────────────────────────────────────────┘                            │           │
 │                                                                              ▼           │
 │  ┌──────────────────────────────────────────────────────────────────────────────────┐    │
 │  │  MCP SERVER SANDBOX (spawned by backend, one process per server)                 │    │
 │  │  /tmp/mcp_repos/{owner}_{repo}  ← git clone --depth 1 (tarball fallback)         │    │
 │  │  isolated venv via `uv run --directory <project>`  ·  npm install/build for Node │    │
 │  │  sanitized env (no backend VIRTUAL_ENV/PYTHONPATH leak)                          │    │
 │  └──────────────────────────────────────────────────────────────────────────────────┘    │
 │                                                                                           │
 │  ┌────────────────────────────┐        ┌─────────────────────────────────────────────┐   │
 │  │ LLM GATEWAY  :4000         │        │ EXTERNAL MCP SERVERS                        │   │
 │  │ apps/llm_gateway           │        │ · remote: streamable-HTTP / SSE endpoints   │   │
 │  │ openai · groq · gemini ·   │        │ · local:  GitHub repos run as stdio procs   │   │
 │  │ litellm router + embeddings│        │   (whatsapp-mcp, mcp-weather, …, any repo)  │   │
 │  └─────────────┬──────────────┘        └─────────────────────────────────────────────┘   │
 │                ▼                                                                          │
 │        Redis :6379 (LiteLLM caching / rate limiting)                                      │
 └───────────────────────────────────────────────────────────────────────────────────────────┘
```

### Microservice Roles

| Component | Directory | Port | Primary Responsibility |
| :--- | :--- | :---: | :--- |
| **Frontend UI** | `web/` | `3000` | Next.js 15 App Router interface. Zustand auth state (`stores/auth-store.ts`), silent JWT refresh interceptor (`lib/api.ts`), role-gated routes (`/vendor`, `/tenant`, `/user`). Talks directly to `:8001` (auth) and `:8002` (vendor resources). |
| **Auth Service** | `apps/auth/` | `8001` | User identities, Tenants, Workspaces, Argon2id passwords, Google OIDC SSO, RS256 JWKS token issuing, audit events. Also mounts the vendor-resources router under `/api/v1/vendor/resources` (parity with backend). |
| **Backend Service** | `apps/backend/` | `8002` | Vendor Resources subsystem: **Universal MCP Engine** (analyze → register → connect), REST tool ingestion, Vault (Fernet) encryption, tenant grants, catalog. Spawns MCP servers as sandboxed subprocesses. |
| **LLM Gateway** | `apps/llm_gateway/` | `4000` | Unified provider abstraction (OpenAI, Groq, Gemini, LiteLLM router). Chat completion + embeddings (default embedding provider: Gemini). |
| **Redis** | `redis:7-alpine` | `6379` | LiteLLM gateway caching / rate-limiting backend. |
| **Central Database** | `data/auth.db` / `db` | 5432 opt | Single SQLAlchemy 2.0 async database — SQLite on the `./data` volume by default, Postgres 16 container via `DATABASE_URL`. Houses tenant, user, resource, grant, and audit tables shared by auth + backend. |

---

## 2. 3-Tier Security & Authentication Hierarchy

All authorization is anchored on a **3-Tier Identity Hierarchy**:

```
Tier 1: Vendor User (Platform Admin)  ──►  Owns & operates the SaaS platform
                                           
Tier 2: Tenant (Customer Organization)──►  Container for company users & workspaces
                                           
Tier 3: User & Workspace               ──►  Individual user inside tenant working in scoped workspace
```

### Role Model & Token Claims

| Role Name | Scope | Capabilities & Permissions |
| :--- | :--- | :--- |
| **`vendor_admin`** | Platform-wide | Manages tenants, provisions global MCP/REST tools, grants resources to tenants, views platform logs. |
| **`tenant_admin`** | Single Tenant | Invites company members, assigns tenant roles, manages workspaces, views tenant audit trail. |
| **`tenant_user`** | Single Tenant | Belongs to a tenant. Inherits all tools/MCP resources granted to their tenant ID by vendor admin. |
| **`solo_user`** | Personal Account | Standalone account. Directly accesses all Global Vendor Resources for personal AI agent creation. |

### Standard JWT Token Payload (`RS256`)

Every request to `apps/auth` or `apps/backend` carries a Bearer JWT:

```json
{
  "sub": "u-3001",
  "tid": "t-2001",
  "wid": "w-4001",
  "role": "tenant_user",
  "type": "access",
  "iss": "enterprise-ai-auth",
  "aud": "enterprise-ai",
  "exp": 1787754317
}
```

* `sub` (Subject): User ID (`users.id`).
* `tid` (Tenant ID): Tenant ID (`tenants.id`) — used for per-tenant Row-Level Security (RLS).
* `wid` (Workspace ID): Active workspace ID (`workspaces.id`).
* `role`: Active user role used by FastAPI `require_roles(...)` guards.

---

## 3. Detailed Flow of Each Component with Authentication

```
+-----------------------------------------------------------------------------------+
|                        COMPONENT FLOW & AUTHENTICATION DIAGRAM                    |
+-----------------------------------------------------------------------------------+

 ┌──────────┐            ┌──────────┐            ┌───────────┐            ┌──────────┐
 │  Client  │            │   Web    │            │   Auth    │            │ Backend  │
 │ (Browser)│            │ (Next.js)│            │(Port 8001)│            │(Port 8002│
 └────┬─────┘            └────┬─────┘            └─────┬─────┘            └────┬─────┘
      │                       │                        │                       │
      │ 1. POST /auth/login   │                        │                       │
      ├──────────────────────►│                        │                       │
      │                       │ 2. Forward Credentials │                       │
      │                       ├───────────────────────►│                       │
      │                       │                        │ 3. Verify Argon2id    │
      │                       │                        │    & Issue JWT        │
      │                       │ 4. { access, refresh } │◄──────────────────────┤
      │                       │◄───────────────────────┤                       │
      │ 5. Store in Zustand   │                        │                       │
      │◄──────────────────────┤                        │                       │
      │                       │                        │                       │
      │ 6. GET /vendor/resources/catalog               │                       │
      │    Authorization: Bearer <token>               │                       │
      ├───────────────────────────────────────────────────────────────────────►│
      │                                                                        │ 7. Verify JWT
      │                                                                        │    & Role Guard
      │                                                                        │ 8. Filter Catalog
      │                                                                        │    by tenant_id
      │ 9. Return Authorized Tools & MCP Servers                               │
      │◄───────────────────────────────────────────────────────────────────────┤
```

### A. Authentication Component Flow (`apps/auth`)

1. **Local Authentication**:
   - User submits `email` & `password`.
   - `apps/auth/src/api/v1/auth/service.py` queries `users` table, verifies password via Argon2id (`src/core/security.py`).
   - Issues short-lived Access Token (15 min) and long-lived Refresh Token (7 days).

2. **SSO / Google OAuth2 Authentication (PKCE)**:
   - Client calls `GET /api/v1/sso/initiate` -> Returns authorization URL with state & PKCE `code_challenge`.
   - User authorizes via Google -> Redirects to `GET /api/v1/sso/callback?code=...`.
   - Backend exchanges code for id_token, matches or provisions `User` row, and returns JWT payload.

3. **Silent Token Refresh**:
   - When Access Token expires (401 response in client), `web/lib/api.ts` transparently calls `POST /auth/refresh` with the refresh token.
   - Rotates tokens and retries the failed API call without interrupting the user.

---

### B. Frontend Component Flow (`web/`)

1. **State Persistence (`stores/auth-store.ts`)**:
   - Uses Zustand with LocalStorage persistence to retain `accessToken`, `refreshToken`, and user payload.
2. **API Client Request Interceptor (`lib/api.ts`)**:
   - Automatically attaches `Authorization: Bearer <accessToken>` to every API call sent to `8001` or `8002`.
   - Intercepts `401 Unauthorized` responses and triggers silent token refresh.
3. **Role-Gated Route Protection (`components/protected-dashboard.tsx`)**:
   - Checks user role from store.
   - `/vendor` -> Required: `vendor_admin`.
   - `/tenant` -> Required: `tenant_admin`.
   - `/user` -> Required: `tenant_user` or `solo_user`.

---

### C. Backend Subsystem Flow (`apps/backend/vendor_resources`)

1. **Auth Verification Guard**:
   - Reuses `src/api/deps.py` (`get_current_user`, `require_roles`) via absolute imports from `apps/auth`.
   - Decodes the RS256 JWT signature against the auth service's JWKS, extracts `tid` (tenant) and `role`.
   - Vendor-admin-only guard on all management routes: `_admin = Depends(require_roles(Roles.VENDOR_ADMIN))`.

2. **Vendor Admin API surface** (`/api/v1/vendor/resources`):

   | Method & Path | Purpose |
   | :--- | :--- |
   | `POST /mcp/analyze-repo` | Analyze a GitHub repo **without registering** — detects transport, entry command, auth type, `env_vars`, and tool list. |
   | `POST /mcp/detect` | Probe a URL/command for transport + auth type. |
   | `POST /mcp` (201) | Register an MCP server definition in DB — persists detected transport, entry command, and required credential fields without requiring credentials at creation time. |
   | `GET /mcp` | List registered MCP servers (vendor admin). |
   | `POST /mcp/{id}/connect` | **Test Connection & Tool Discovery**: Accepts primary credentials, resolves auth via Fernet Vault / OAuth engine, spawns stdio/remote server, runs `mcp.initialize()` + `tools/list` discovery, and persists `bound_tools`. |

3. **Official 2-Step Registration → Test Connection Lifecycle**:
   - **Step 1 (Register)**: `create_mcp_server()` persists the server definition and detected credential key names (`required_env_vars` / `auth_config`) so server registration is fast and never blocked by missing keys.
   - **Step 2 (Test Connection & Discover Tools)**: `connect_registered_server()` is triggered when clicking **Test Connection** (Link icon). It prompts for primary credentials (`CLIENT_ID`, `NOTION_TOKEN`, etc.), encrypts keys into the Fernet Vault, spawns the stdio/remote process, discovers tools, and binds them to the server row.

4. **Tenant Resource Granting Flow**:
   - `POST /api/v1/vendor/resources/grants` -> Writes mapping to `tenant_resource_grants` table (`tenant_id`, `resource_id`).
   - Instantly grants access to all members belonging to that `tenant_id`.

---

### D. Universal MCP Engine — Connection Pipeline (`services/mcp_client.py`)

This is the vendor-agnostic engine that takes any MCP server — a URL or an arbitrary GitHub repo — from analysis to a live, tool-discovered connection:

```text
 ┌────────────────────────────────────────────────────────────────────────────────────┐
 │                             MCP CONNECTION DECISION FLOW                           │
 └────────────────────────────────────────────────────────────────────────────────────┘

        connect_mcp_server(server_url, credentials, transport, auth_type,
                           source_repo_url, env_vars)
                                   │
                ┌──────────────────┴───────────────────┐
                ▼                                      ▼
     transport == "stdio"                     remote (auto-detect default)
                │                                      │
                ▼                                      ▼
 ┌──────────────────────────────────┐   ┌─────────────────────────────────────────┐
 │ 1. SANITIZE ENV (_sanitize_stdio │   │ 1. BUILD AUTH HEADERS (_build_auth_     │
 │    _env) — drop VIRTUAL_ENV,     │   │    headers) from credentials + auth_type│
 │    PYTHONPATH/PYTHONHOME,        │   │    (none / api_key / bearer / basic /   │
 │    .venv/* PATH entries          │   │    custom-header)                       │
 │ 2. INJECT ENV (env_vars upper-   │   └────────────────────┬────────────────────────┘
 │    cased, skip null/empty) then  │                        │
 │    credentials (uppercase keys)  │                        ▼
 │ 3. PREPARE REPO (_prepare_local_ │   ┌─────────────────────────────────────────┐
 │    repo_stdio):                  │   │ 2. ATTEMPT HANDSHAKES IN ORDER          │
 │    · cache hit w/ manifest →     │   │    · transport="sse"    → [sse]         │
 │      reuse, NO re-clone          │   │    · transport="http"   → [streamable   │
 │    · stale/partial cache →       │   │      _http, sse fallback]               │
 │      rmtree + re-fetch           │   │ 3. MCP INITIALIZE handshake             │
 │    · git clone --depth 1        │   │    → server_info, protocol_version,     │
 │      (fallback: GitHub tarball) │   │      ListTools discovery                │
 │    · Node: npm install + build   │   │ 4. RETURN {transport, bound_tools,      │
 │    · Python: pick entry →        │   │    tools, server_info, auth_type}       │
 │      uv run --directory <proj>   │   └─────────────────────────────────────────┘
 │      (isolated venv, correct CWD)│
 │ 4. SPAWN StdioServerParameters   │
 │    (command, args, env, cwd)     │
 │ 5. MCP INITIALIZE + ListTools    │
 └──────────────────────────────────┘
```

**Stdio repo preparation details** (`_prepare_local_repo_stdio` → `_pick_local_entry`):

- **Only clones when necessary** — a GitHub URL / `git+` command triggers a fetch; a self-resolving package runner (`npx -y @org/pkg`, `uvx …`, `pipx …`) never does; `source_repo_url` alone is treated as registration metadata.
- **Repo cache** at `/tmp/mcp_repos/{owner}_{repo}` — reused as-is when a project manifest exists at the root **or any immediate subdirectory** (e.g. `lharries/whatsapp-mcp → whatsapp-mcp-server/`); stale/manifest-less leftovers are removed before re-clone; a failed clone cleans its partial dir before the tarball fallback (GitHub tarball, `main`→`master`, extracted with `filter="data"`).
- **Entry resolution order** — Node: `dist|build/index.js` → `package.json.bin` → `main` → root `index.js`; Python: root `server.py|main.py|mcp_server.py|app.py` → `[tool.mcp.servers]` command → `[project.scripts]` console entry → **`uv run --directory <project> <script>`** (installs the server's own deps into an isolated venv and sets the correct CWD for nested project roots) → `__main__.py` via `runpy` → recursive `**/server.py` fallback.
- **Credential/env injection happens after sanitization**, so tenant-provided `env_vars` and credentials always win over inherited process state.

---

### E. AI Compiler & Catalog Execution Flow (`apps/llm_gateway` & `catalog_engine`)

```
 ┌───────────────────────┐
 │   User Prompt Canvas  │ "Verify invoice > $5,000 against CFO Policy PDF and send Slack alert"
 └───────────┬───────────┘
             │
             ▼
 ┌───────────────────────┐
 │ Catalog Engine Filter │  • If solo_user   ──► Pull Global Resources (is_global = True)
 └───────────┬───────────┘  • If tenant_user ──► Pull Resources granted to user's tenant_id
             │
             ▼
 ┌───────────────────────┐
 │ Semantic Tool Matcher │ Embeds prompt & performs vector similarity search against tool descriptions
 └───────────┬───────────┘
             │
             ▼
 ┌───────────────────────┐
 │  Schema Compressor    │ Strips verbose comments from JSON schemas to minimize token consumption
 └───────────┬───────────┘
             │
             ▼
 ┌───────────────────────┐
 │  LLM Compiler Engine  │ Generates validated Pydantic v2 `CompiledAgentSpec` DAG (Nodes & Edges)
 └───────────────────────┘
```

---

## 4. End-to-End Data & Security Isolation Matrix

| Operation | Authentication Guard | Database Scoping Logic |
| :--- | :--- | :--- |
| **Fetch Catalog** | `get_current_user` | Filters `vendor_tools` & `vendor_mcp_servers` where `is_global=True` (for `solo_user`) OR `id IN (SELECT resource_id FROM tenant_resource_grants WHERE tenant_id = user.tenant_id)`. |
| **Store MCP Credentials** | `require_roles(tenant_admin, vendor_admin)` | Validates target `tenant_id` matches `user.tenant_id`. Encrypts credentials via AES-256 Fernet key. |
| **Execute Tool / MCP Call** | `get_current_user` | Validates user has active workspace membership (`workspaces` table check) and logs event to `audit_events`. |
| **Manage Tenant Members** | `require_roles(tenant_admin)` | Restricts user creation/updates strictly to `user.tenant_id`. |

---

## 5. Role Interaction & 3-Layer Universal MCP Engine Architecture

### A. How Each Role Interacts with the Platform

```
+---------------------------------------------------------------------------------------------------+
|                                 ROLE INTERACTION & WORKSPACE FLOW                                 |
+---------------------------------------------------------------------------------------------------+

   ┌─────────────────────────┐
   │      VENDOR ADMIN       │ ──► Operates /vendor & /vendor/tools dashboards
   │  (role = vendor_admin)  │ ──► Ingests REST APIs & Registers MCP Servers (SSE/Stdio/GitHub)
   └────────────┬────────────┘ ──► Issues Grants: POST /api/v1/vendor/resources/grants
                │
                │ Grants Resources to Tenant ID
                ▼
   ┌─────────────────────────┐
   │      TENANT ADMIN       │ ──► Operates /tenant dashboard
   │  (role = tenant_admin)  │ ──► Manages Tenant Members (POST /tenant/members) & Workspaces
   └────────────┬────────────┘ ──► Stores Tenant-Specific MCP API Keys & Credentials
                │
                │ Manages Members & Workspaces
                ▼
   ┌─────────────────────────┐
   │       TENANT USER       │ ──► Operates /user & /user/agents workbench
   │   (role = tenant_user)  │ ──► Auto-inherits all MCP tools granted to their Tenant ID
   └─────────────────────────┘ ──► Submits NL Prompts to build & execute AI LangGraph Agents

   ┌─────────────────────────┐
   │        SOLO USER        │ ──► Operates /user workbench on Personal Plan
   │   (role = solo_user)    │ ──► Directly accesses all Global Vendor Resources (is_global = True)
   └─────────────────────────┘ ──► Creates and executes personal workspace AI Agents
```

---

### B. The 3-Layer Universal Architecture (Source Entry ➔ Transport ➔ Auth)

```text
                         ┌─────────────────────────┐
                         │   LAYER 1: ENTRY SOURCE │
                         │  (any MCP, any vendor)  │
                         └────────────┬────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     │                                 │
                     ▼                                 ▼
        ┌──────────────────────────┐       ┌──────────────────────────┐
        │   OPTION 1: REMOTE MCP   │       │   OPTION 2: GITHUB MCP   │
        │      (URL Endpoint)      │       │          REPO            │
        │ https://example.com/mcp  │       │ POST /mcp/analyze-repo   │
        └────────────┬─────────────┘       │  → clone/tarball cache   │
                     │                     │  → parse entry & auth    │
                     ▼                     │  → auto-connect probes   │
              ┌─────────────┐              └────────────┬─────────────┘
              │  TRANSPORT  │                           │
              │  PROBING    │                           ▼
              └──────┬──────┘                    ┌─────────────┐
                     │                           │ LAYER 2:    │
              ┌──────┼─────────┐                 │ TRANSPORT   │
              │      │         │                 └──────┬──────┘
              ▼      ▼         ▼                        │
           Stream   SSE      HTTP              ┌────────┴────────┐
           able     Legacy                     │                 │
           HTTP                                ▼                 ▼
              │                              stdio           HTTP/SSE
              │                          (isolated uv/npm       │
              │                           sandbox under        │
              │                           /tmp/mcp_repos)      │
              └──────────────┬─────────────────┴─────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │     LAYER 3:     │
                    │  AUTHENTICATION  │
                    │ (resolved at     │
                    │  connect time)   │
                    └────────┬─────────┘
                             │
       ┌──────────┬──────────┼──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
     NONE      API KEY    BEARER     OAUTH      BASIC     CUSTOM
                           TOKEN       2.0        AUTH      HEADER
                              │
                              ▼
                     ┌─────────────────┐
                     │ ENV VARIABLES   │
                     │ + {field} subst.│
                     │ in stdio command│
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ TEST CONNECTION │
                     │ (auto at reg.,  │
                     │  manual /connect)│
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │   MCP CONNECT   │
                     │ tools discovered│
                     └─────────────────┘
```
---

### C. Testing Vendor Admin Capabilities & MCP Endpoints

#### 1. Automated Pytest Verification Command
```bash
# Run all Vendor Resource & MCP integration tests (96 tests as of 2026-09)
uv run pytest apps/backend/vendor_resources/tests/
```

#### 2. Universal MCP Flow via cURL — Analyze → Register → Connect

```bash
# Step 0: Login as Vendor Admin to get Access Token
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"priya@enterpriseai.io","password":"VendorAdminPassword123!"}' \
  | jq -r '.access_token')

# Step 1: Analyze ANY GitHub repo (no registration — dry-run detection)
curl -X POST http://localhost:8002/api/v1/vendor/resources/mcp/analyze-repo \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/lharries/whatsapp-mcp"}'
# → returns detected transport (stdio), entry command, auth_type, env_vars, tools

# Step 2: Register the MCP Server (creates server definition in DB)
curl -X POST http://localhost:8002/api/v1/vendor/resources/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "WhatsApp MCP",
    "transport": "stdio",
    "server_url": "npx -y whatsapp-mcp",
    "source_repo_url": "https://github.com/lharries/whatsapp-mcp",
    "is_global": true
  }'
# → 201 Created; persists server row & detected auth_config

# Step 3: Test Connection & Discover Tools (passes credentials, encrypts in vault, discovers tools)
curl -X POST http://localhost:8002/api/v1/vendor/resources/mcp/<server_id>/connect \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "credentials": {
      "WHATSAPP_TOKEN": "secret_token_123"
    }
  }'
# → 200 OK; returns discovered tools, protocol version, and binds tools to server row

# Step 4: Grant an MCP Server to a specific Tenant ID
curl -X POST http://localhost:8002/api/v1/vendor/resources/grants \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant_acme_corp",
    "resource_type": "mcp",
    "resource_id": "mcp_server_id_here"
  }'

# Step 5: Test Tenant User Catalog Visibility
USER_TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@acme.com","password":"UserPassword123!"}' \
  | jq -r '.access_token')

curl -X GET "http://localhost:8002/api/v1/vendor/resources/catalog?q=whatsapp" \
  -H "Authorization: Bearer $USER_TOKEN"
```
