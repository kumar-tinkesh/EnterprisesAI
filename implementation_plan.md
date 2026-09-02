# Master Implementation Plan: Universal MCP Engine & Dynamic Frontend Integration

This master implementation plan details the architecture and step-by-step code changes required to build the **Universal MCP Ingestion Engine** across both the **FastAPI Backend Subsystem (`apps/backend/vendor_resources`)** and the **Next.js Frontend Dashboard (`web/`)**, aligned directly with [PROJECT_ARCHITECTURE_AND_AUTH_FLOWS.md](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/docs/PROJECT_ARCHITECTURE_AND_AUTH_FLOWS.md).

---

## 🏗️ 1. Architecture Alignment & 3-Tier Hierarchy

The implementation seamlessly integrates into the platform's **3-Tier Multi-Tenant Identity Model**:

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

### Role Model & Rights Matrix

| Role | Scope | MCP Ingestion & Execution Rights |
| :--- | :--- | :--- |
| **`vendor_admin`** | Platform-Wide | Registers MCP Servers (Remote URL or GitHub Repo), triggers dynamic code analysis, provisions global tools, and grants MCP access to Tenants. |
| **`tenant_admin`** | Single Tenant | Stores tenant-specific MCP API keys and credentials in the Fernet AES-256 Vault. |
| **`tenant_user`** | Single Tenant | Auto-inherits access to all MCP tools granted to their Tenant ID; executes tools via AI Agent Compiler. |
| **`solo_user`** | Personal Plan | Directly accesses all Global Vendor MCP Servers for personal workspace agent compilation. |

---

## 🌐 2. The 3-Layer Universal MCP Engine Architecture

The engine strictly separates **Source Entry**, **Transport**, and **Authentication** into 3 independent layers with **0 hardcoded vendor rules**:

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
                     └────────┬────────┘
                              │
                              ▼
           ┌───────────────────────────────────────┐
           │ JSON-RPC Handshake: `mcp.initialize`  │
           │ Tool Auto-Discovery: `tools/list`     │
           │ Save to `./data/auth.db` bound_tools  │
           └───────────────────────────────────────┘
```

---

## 🎨 3. Frontend UI Component Workflow (`web/`)

```
+---------------------------------------------------------------------------------------------------+
|                            NEXT.JS VENDOR MCP DASHBOARD MODAL FLOW                                |
+---------------------------------------------------------------------------------------------------+

                    Click [ + Register MCP Server ]
                                  │
                                  ▼
      ┌───────────────────────────────────────────────────────────────┐
      │ DUAL-TAB REGISTER MCP MODAL (`web/app/vendor/tools/page.tsx`) │
      ├───────────────────────────────┬───────────────────────────────┤
      │  TAB 1: Remote MCP Endpoint   │  TAB 2: GitHub Repository URL │
      └───────────────┬───────────────┴───────────────┬───────────────┘
                      │                               │
                      │                               │ Vendor enters: https://github.com/org/repo
                      │                               │ Clicks [ 🔍 Analyze Repository ]
                      │                               ▼
                      │               Calls `vendorApi.analyzeRepo(repoUrl)`
                      │                               │
                      │                               ▼
                      │               ┌──────────────────────────────┐
                      │               │ REPO ANALYSIS REPORT CARD    │
                      │               ├──────────────────────────────┤
                      │               │ ✓ Transport: stdio / Docker  │
                      │               │ ✓ Runtime: Node / Python / Go│
                      │               │ ✓ Command: npx -y <pkg>      │
                      │               │                              │
                      │               │ Required Environment Keys:   │
                      │               │ 🔑 GITHUB_TOKEN  [_________] │
                      │               │ 🔑 SLACK_API_KEY [_________] │
                      │               └───────────────┬──────────────┘
                      │                               │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                        Click [ 🚀 Register & Discover Tools ]
                                      │
                                      ▼
                      Calls `vendorApi.createMCPServer(...)`
                                      │
                                      ▼
      ┌───────────────────────────────────────────────────────────────┐
      │ TOOLS DISCOVERY MODAL (`ToolsModal`)                          │
      ├───────────────────────────────────────────────────────────────┤
      │ ✓ Transport: stdio / Streamable HTTP                         │
      │ ✓ Discovered Tools (3):                                       │
      │   - charge_card                                               │
      │   - refund_payment                                            │
      │   - get_customer                                              │
      └───────────────────────────────────────────────────────────────┘
```

---

## User Review Required

> [!IMPORTANT]
> **Subprocess & Sandboxing Policy**:
> Local `stdio` MCP servers spawn subprocesses (`npx`, `python`, `docker`). In production environments, `docker run` sandboxing is recommended to prevent untrusted repo code execution on the host machine.

---

## Open Questions

None. The proposed contracts extend existing `vendor_resources` schemas and database models cleanly without breaking changes.

---

## Proposed Changes

### Backend Subsystem (`apps/backend/vendor_resources`)

#### [NEW] [apps/backend/vendor_resources/services/repo_analyzer.py](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/apps/backend/vendor_resources/services/repo_analyzer.py)
- Implement `analyze_github_repo(repo_url: str) -> AnalyzeRepoResponse`:
  - **Dynamic Shallow Fetch**: Fetches manifest tree via Git shallow clone (`--depth 1`) or GitHub REST API.
  - **Manifest Scanner (0 Hardcoded Rules)**:
    - Scans `Dockerfile` / `docker-compose.yml` ➔ `runtime: "docker"`, `command: "docker"`, `args: ["run", "--rm", "-i"]`.
    - Scans `package.json` ➔ Node.js stdio (`npx -y <pkg>`).
    - Scans `pyproject.toml` / `requirements.txt` ➔ Python FastMCP stdio (`python server.py`).
    - Scans `go.mod` / `Cargo.toml` ➔ Go/Rust binary stdio (`go run .`).
    - Scans `README.md` ➔ Checks for remote HTTPS endpoint (`https://.../mcp` or `/sse`).
  - **Dynamic Environment Secret Extractor**:
    - Scans `.env.example`, README code blocks, and source code using regex `r"\b([A-Z0-9_]{2_}_(?:TOKEN|KEY|SECRET|PASSWORD|AUTH|API|ID))\b"`.
    - Returns array of detected key names (e.g., `["GITHUB_PERSONAL_ACCESS_TOKEN"]`).

#### [MODIFY] [apps/backend/vendor_resources/schemas.py](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/apps/backend/vendor_resources/schemas.py)
- Add `AnalyzeRepoRequest`:
  - `repo_url: str`
- Add `AnalyzeRepoResponse` contract.
- Update `ConnectMCPServerRequest`:
  - Add `source_repo_url: str | None = None`
  - Add `env_vars: dict[str, str] | None = None`

#### [MODIFY] [apps/backend/vendor_resources/models.py](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/apps/backend/vendor_resources/models.py)
- Add `source_repo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)` to `VendorMCPServer`.

#### [MODIFY] [apps/backend/vendor_resources/services/mcp_service.py](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/apps/backend/vendor_resources/services/mcp_service.py)
- Update `create_mcp_server()` to pass `env_vars` to `connect_mcp_server()` and save `source_repo_url`.

#### [MODIFY] [apps/backend/vendor_resources/router.py](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/apps/backend/vendor_resources/router.py)
- Add endpoint `POST /mcp/analyze-repo` (guarded by `require_roles(Roles.VENDOR_ADMIN)`).

---

### Frontend Components (`web/`)

#### [MODIFY] [web/lib/api.ts](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/web/lib/api.ts)
- Add `AnalyzeRepoResponse` interface:
  ```ts
  export interface AnalyzeRepoResponse {
    detected: boolean;
    transport: "stdio" | "streamable_http" | "sse";
    runtime: "node" | "python" | "docker" | "go" | "remote" | "custom";
    suggested_command: string | null;
    remote_endpoint: string | null;
    required_env_vars: string[];
    auth_type: string;
    hints: string[];
  }
  ```
- Add API method `analyzeRepo`:
  ```ts
  analyzeRepo: (token: string, repoUrl: string) =>
    request<AnalyzeRepoResponse>(`${VR}/mcp/analyze-repo`, {
      method: "POST",
      body: JSON.stringify({ repo_url: repoUrl }),
    }, token, BACKEND_API_URL),
  ```

#### [MODIFY] [web/app/vendor/tools/page.tsx](file:///home/AbhishekPrajapati/Desktop/EnterpriseAI/web/app/vendor/tools/page.tsx)
- Redesign `CreateMCPModal`:
  - **Tab 1: Remote MCP Endpoint** (Input for live `https://...` URL).
  - **Tab 2: GitHub Repository URL** (Input for `https://github.com/...` with **Analyze Repository** button).
- Add dynamic state management for repo analysis:
  - `isAnalyzing: boolean`
  - `analysisResult: AnalyzeRepoResponse | null`
  - `envValues: Record<string, string>` (dynamically bound to detected environment keys).
- Automatically switch from analysis feedback card to pre-filled registration form.
- Show discovered tools immediately in `ToolsModal` upon successful registration & handshake!

---

## 🧪 Verification Plan

### Automated Tests
1. **Repo Analyzer Unit Tests** (`apps/backend/vendor_resources/tests/test_repo_analyzer.py`):
   - Test Node `package.json` stdio detection.
   - Test Python `pyproject.toml` stdio detection.
   - Test `Dockerfile` container detection.
   - Test `README.md` remote URL extraction.
   - Test `.env.example` regex secret key extraction.
2. **Router Integration Tests** (`apps/backend/vendor_resources/tests/test_router.py`):
   - Test `POST /api/v1/vendor/resources/mcp/analyze-repo`.
   - Test `POST /api/v1/vendor/resources/mcp` with `source_repo_url` and `env_vars`.
3. **Frontend Vitest Component Tests**:
   - Run `pnpm test` in `web/` to verify zero breaking UI changes.

### Manual Verification
- Open Next.js UI at `http://localhost:3000/vendor/tools`.
- Click **[ Register MCP Server ]** -> Select **GitHub Repository URL** tab.
- Enter `https://github.com/github/github-mcp-server` and click **[ Analyze Repository ]**.
- Verify detected `stdio`/`docker` runtime, auto-rendered `GITHUB_TOKEN` secret input field, and test connection tool discovery.
