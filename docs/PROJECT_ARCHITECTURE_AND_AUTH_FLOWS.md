# EnterpriseAI — Architecture & Component Authentication Flows

This document provides a comprehensive technical overview of the **EnterpriseAI Platform Architecture**, detailing the **Flow of Each Component**, the **3-Tier Multi-Tenant Security Hierarchy**, the **End-to-End Authentication & Execution Model**, and the **Role Interaction & MCP Server Lifecycle Guide**.

---

## 1. System Overview & Component Topology

EnterpriseAI is structured into microservices with centralized shared database access and standardized authentication token contracts:

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                         ENTERPRISE AI PLATFORM                              │
 │                                                                             │
 │  ┌─────────────────┐       ┌─────────────────┐       ┌──────────────────┐  │
 │  │   Next.js Web   │       │   Auth Service  │       │ Backend Service  │  │
 │  │    (Frontend)   │       │  (apps/auth)    │       │  (apps/backend)  │  │
 │  │    Port 3000    │       │    Port 8001    │       │    Port 8002     │  │
 │  └────────┬────────┘       └────────┬────────┘       └────────┬─────────┘  │
 │           │                         │                         │            │
 │           │ REST / JWT              │ DB Session / RLS        │ FastAPI    │
 │           ▼                         ▼                         ▼            │
 │  ┌───────────────────────────────────────────────────────────────────────┐  │
 │  │                     LLM Gateway (apps/llm_gateway)                    │  │
 │  │           LiteLLM Provider Router (OpenAI, Groq, Gemini)              │  │
 │  └──────────────────────────────────┬────────────────────────────────────┘  │
 │                                     │                                       │
 │                                     ▼                                       │
 │                  ┌─────────────────────────────────────┐                    │
 │                  │    Central Database (data/auth.db)   │                    │
 │                  │       SQLAlchemy 2.0 / SQLite       │                    │
 │                  └─────────────────────────────────────┘                    │
 └─────────────────────────────────────────────────────────────────────────────┘
```

### Microservice Roles

| Component | Directory | Port | Primary Responsibility |
| :--- | :--- | :---: | :--- |
| **Frontend UI** | `web/` | `3000` | Next.js 15 App Router interface. Handles state management (`zustand`), form validation (`zod`), and protected dashboard routes. |
| **Auth Service** | `apps/auth/` | `8001` | Manages User identities, Tenants, Workspaces, Argon2id passwords, OIDC/Google SSO, JWKS token issuing, and Audit Events. |
| **Backend Service** | `apps/backend/` | `8002` | Vendor Resources Subsystem: MCP Servers (SSE/Stdio), REST Tool Ingestion, Vault encryption, Tenant Grants, and AI Compiler. |
| **LLM Gateway** | `apps/llm_gateway/` | N/A | Provider abstraction for LiteLLM, Groq, Gemini, and OpenAI. Embeddings generation and structured prompt execution. |
| **Central Database** | `data/auth.db` | N/A | Single SQLite/Postgres database housing all tenant, user, resource, grant, and audit tables. |

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

### Standard JWT Token Payload (`RS256` / `HS256`)

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
* `role`: Active user role used by FastAPI `@require_roles(...)` guards.

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
   - Decodes JWT signature, extracts `tenant_id` and `role`.

2. **Resource Provisioning Flow (Vendor Admin)**:
   - `POST /api/v1/vendor/resources/mcp` -> Connects to MCP Server via SSE/Stdio, auto-discovers tools via `mcp.initialize()`.
   - `POST /api/v1/vendor/resources/tools` -> Ingests REST/OpenAPI schema. Encrypts sensitive keys via Vault driver (`core/vault.py`).

3. **Tenant Resource Granting Flow**:
   - `POST /api/v1/vendor/resources/grants` -> Writes mapping to `tenant_resource_grants` table (`tenant_id`, `resource_id`).
   - Instantly grants access to all members belonging to that `tenant_id`.

---

### D. AI Compiler & Catalog Execution Flow (`apps/llm_gateway` & `catalog_engine`)

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

```
                         ┌─────────────────────────┐
                         │   LAYER 1: ENTRY SOURCE │
                         └────────────┬────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     │                                 │
                     ▼                                 ▼
        ┌──────────────────────────┐       ┌──────────────────────────┐
        │   OPTION 1: REMOTE MCP   │       │   OPTION 2: GITHUB MCP   │
        │      (URL Endpoint)      │       │          REPO            │
        │ https://example.com/mcp  │       │ https://github.com/org/  │
        └────────────┬─────────────┘       └────────────┬─────────────┘
                     │                                  │
                     ▼                                  ▼
              ┌─────────────┐                    ┌─────────────┐
              │  TRANSPORT  │                    │   ANALYZE   │
              │  PROBING    │                    │    REPO     │
              └──────┬──────┘                    └──────┬──────┘
                     │                                  │
              ┌──────┼─────────┐                        │
              │      │         │                        ▼
              ▼      ▼         ▼                 ┌─────────────┐
           Stream   SSE      HTTP                │ LAYER 2:    │
           able     Legacy                       │ TRANSPORT   │
           HTTP                                  └──────┬──────┘
              │                                         │
              │                                ┌────────┴────────┐
              │                                │                 │
              │                                ▼                 ▼
              │                              stdio           HTTP/SSE
              │                                │                 │
              └──────────────┬─────────────────┴─────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │     LAYER 3:     │
                    │  AUTHENTICATION  │
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
                     │ (mostly stdio)  │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ TEST CONNECTION │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │   MCP CONNECT   │
                     └─────────────────┘
```

---

### C. Testing Vendor Admin Capabilities & MCP Endpoints

#### 1. Automated Pytest Verification Command
```bash
# Run all Vendor Resource & MCP integration tests
uv run pytest apps/backend/vendor_resources/tests/
```

#### 2. Testing MCP Server Registration via cURL

```bash
# Step 1: Login as Vendor Admin to get Access Token
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"priya@enterpriseai.io","password":"VendorAdminPassword123!"}' \
  | jq -r '.access_token')

# Step 2: Register a new Global MCP Server
curl -X POST http://localhost:8002/api/v1/vendor/resources/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Financial Services MCP",
    "transport": "sse",
    "server_url": "http://localhost:9090/sse",
    "is_global": true
  }'

# Step 3: Grant an MCP Server to a specific Tenant ID
curl -X POST http://localhost:8002/api/v1/vendor/resources/grants \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant_acme_corp",
    "resource_type": "mcp",
    "resource_id": "mcp_server_id_here"
  }'

# Step 4: Test Tenant User Catalog Visibility
USER_TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@acme.com","password":"UserPassword123!"}' \
  | jq -r '.access_token')

curl -X GET "http://localhost:8002/api/v1/vendor/resources/catalog?q=refund" \
  -H "Authorization: Bearer $USER_TOKEN"
```
