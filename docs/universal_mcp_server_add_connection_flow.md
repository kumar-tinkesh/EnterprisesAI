# Universal MCP Server Add & Connection Flow

## 1. Goal

The MCP Marketplace/Engine should allow a vendor to add an MCP server from either:

1. A **Remote MCP URL**
2. A **GitHub / source repository URL**

The system must automatically analyze the source, detect the runtime connection method, detect authentication requirements, build a normalized configuration, and only connect during the explicit **Test Connection & Discover Tools** step.

The engine must remain **vendor-agnostic**. Do not create separate connection logic for GitHub, Stripe, Xero, Salesforce, Odoo, etc.

---

# 2. High-Level Flow

```text
                           ┌──────────────────────┐
                           │      VENDOR / USER   │
                           │      Add MCP Server  │
                           └──────────┬───────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
                    ▼                                   ▼
          ┌───────────────────┐               ┌────────────────────┐
          │ Remote MCP URL    │               │ GitHub / Source    │
          │ https://.../mcp   │               │ Repository URL     │
          └─────────┬─────────┘               └─────────┬──────────┘
                    │                                   │
                    │                                   ▼
                    │                         ┌────────────────────┐
                    │                         │ Clone / Download   │
                    │                         │ + Resolve Subpath  │
                    │                         └─────────┬──────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      ▼
                         ┌────────────────────────┐
                         │     MCP REPO ANALYZER  │
                         └────────────┬───────────┘
                                      │
              ┌───────────────────────┼────────────────────────┐
              │                       │                        │
              ▼                       ▼                        ▼
       ┌──────────────┐       ┌──────────────┐       ┌────────────────┐
       │ Transport    │       │ Runtime      │       │ Authentication │
       │ Detection    │       │ Detection    │       │ Detection      │
       └──────┬───────┘       └──────┬───────┘       └───────┬────────┘
              │                      │                       │
              ▼                      ▼                       ▼
       STDIO / HTTP / SSE     Node/Python/Go/etc.    None/API/OAuth/etc.
              │                      │                       │
              └──────────────────────┼───────────────────────┘
                                     ▼
                         ┌────────────────────────┐
                         │ NORMALIZED MCP CONFIG  │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ STEP 1: REGISTER ONLY  │
                         │ Save server metadata   │
                         └────────────┬───────────┘
                                      │
                                      │ 201 Created
                                      ▼
                         ┌────────────────────────┐
                         │ Server Added           │
                         │ Status: UNCONNECTED    │
                         └────────────┬───────────┘
                                      │
                                      │ User clicks
                                      │ "Test Connection"
                                      ▼
                         ┌────────────────────────┐
                         │ STEP 2: CONNECT        │
                         │ Credential Modal       │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ Encrypt Credentials    │
                         │ Store in Fernet Vault  │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ Generic MCP Client     │
                         └────────────┬───────────┘
                                      │
                   ┌──────────────────┼──────────────────┐
                   │                  │                  │
                   ▼                  ▼                  ▼
             ┌──────────┐      ┌──────────────┐   ┌──────────┐
             │  STDIO   │      │ Streamable   │   │   SSE    │
             │ Adapter  │      │ HTTP Adapter │   │ Adapter  │
             └────┬─────┘      └──────┬───────┘   └────┬─────┘
                  │                   │                  │
                  └───────────────────┼──────────────────┘
                                      ▼
                              ┌───────────────┐
                              │ MCP initialize│
                              └───────┬───────┘
                                      ▼
                              ┌───────────────┐
                              │   tools/list  │
                              └───────┬───────┘
                                      ▼
                              ┌───────────────┐
                              │ Save MCP Tools │
                              └───────┬───────┘
                                      ▼
                              ┌───────────────┐
                              │    VERIFIED   │
                              │  Tools Ready  │
                              └───────────────┘
```

---

# 3. Two Ways to Add an MCP Server

## A. Remote MCP URL

Example:

```text
https://example.com/mcp
```

The URL is already a potential runtime endpoint.

Flow:

```text
Remote URL
   │
   ▼
Probe Endpoint
   │
   ├── MCP / Streamable HTTP detected
   │
   ├── SSE detected
   │
   └── Auth challenge detected
           │
           ▼
      Normalize Config
           │
           ▼
      Register Server
```

Important:

```text
Remote URL = runtime source/endpoint
```

Do not clone or execute a remote MCP endpoint as if it were a Git repository.

---

## B. GitHub / Source Repository

Example:

```text
https://github.com/vendor/project
```

or a monorepo subdirectory:

```text
https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem
```

Flow:

```text
GitHub URL
    │
    ▼
Parse owner/repo/branch/subpath
    │
    ▼
Clone repository
    │
    ├── Git clone succeeds
    │
    └── Git clone fails
            │
            ▼
       Tarball fallback
            │
            └── Both fail → clean 404/400
    │
    ▼
Resolve MCP subdirectory
    │
    ▼
Analyze repository
```

The GitHub URL itself is **not** the MCP runtime endpoint.

---

# 4. Connection Methods

The engine should support three runtime transport methods:

```text
┌───────────────────────────────┐
│       MCP CONNECTION          │
├───────────────────────────────┤
│                               │
│  1. STDIO                     │
│  2. Streamable HTTP           │
│  3. SSE (legacy)              │
│                               │
└───────────────────────────────┘
```

Authentication is a separate layer.

---

# 5. STDIO Connection

STDIO is used when the MCP server runs as a local process.

Typical examples:

```text
npx -y @playwright/mcp
uv run server.py
python server.py
github-mcp-server stdio
node dist/index.js
```

Flow:

```text
                    MCP ENGINE
                        │
                        ▼
                 Spawn Process
                        │
             ┌──────────┴──────────┐
             │                     │
             ▼                     ▼
          stdin                 stdout
             │                     │
             └─────────┬───────────┘
                       ▼
                 JSON-RPC / MCP
                       │
                       ▼
                  initialize
                       │
                       ▼
                   tools/list
```

Normalized config:

```json
{
  "transport_type": "stdio",
  "runtime_type": "node",
  "command": "npx",
  "args": ["-y", "@playwright/mcp"],
  "working_directory": "/repo",
  "auth_type": "none"
}
```

---

# 6. Streamable HTTP Connection

Used by remote HTTP MCP servers.

Typical endpoint:

```text
https://example.com/mcp
```

Flow:

```text
                  MCP ENGINE
                       │
                       ▼
                 HTTP Client
                       │
                       ▼
              POST /mcp
                       │
                       ▼
              MCP initialize
                       │
                       ▼
                 tools/list
                       │
                       ▼
                  MCP Tools
```

With authentication:

```text
MCP ENGINE
    │
    ▼
Credential Resolver
    │
    ▼
Authorization: Bearer <token>
    │
    ▼
POST /mcp
    │
    ▼
initialize
    │
    ▼
tools/list
```

Normalized config:

```json
{
  "transport_type": "streamable_http",
  "endpoint": "https://example.com/mcp",
  "auth_type": "bearer"
}
```

---

# 7. SSE Connection

SSE is a legacy MCP transport that may still exist for compatibility.

Typical evidence:

```text
/sse
text/event-stream
SSEServerTransport
```

Flow:

```text
                  MCP ENGINE
                       │
                       ▼
                  SSE Client
                       │
                       ▼
                GET /sse
                       │
                       ▼
              text/event-stream
                       │
                       ▼
                 MCP Session
                       │
                       ▼
                initialize
                       │
                       ▼
                 tools/list
```

Normalized config:

```json
{
  "transport_type": "sse",
  "endpoint": "https://example.com/sse",
  "auth_type": "bearer"
}
```

Do not assume SSE only because a URL contains `/sse`. Use documentation/source evidence or an actual probe.

---

# 8. Authentication Methods

Transport and authentication must be independent.

```text
                 MCP CONNECTION
                       │
          ┌────────────┼────────────┐
          │            │            │
        STDIO      HTTP/SSE       HTTP
          │            │            │
          └────────────┼────────────┘
                       │
                       ▼
                 AUTHENTICATION
                       │
       ┌───────┬───────┼────────┬────────┐
       │       │       │        │        │
      None   API Key  Bearer  OAuth2   Basic
                       │
                       ├── OAuth2 + PKCE
                       ├── Environment
                       ├── Custom Headers
                       ├── JWT
                       └── mTLS
```

Recommended normalized values:

```text
none
api_key
bearer
oauth2
oauth2_pkce
basic
environment
custom_header
jwt
mtls
unknown
```

---

# 9. STDIO + Authentication

STDIO commonly receives credentials through environment variables.

Example:

```text
MCP Engine
    │
    ▼
Credential Vault
    │
    ▼
Decrypt at runtime
    │
    ▼
Environment
    │
    ├── GITHUB_PERSONAL_ACCESS_TOKEN
    ├── BRAVE_API_KEY
    └── STRIPE_API_KEY
    │
    ▼
Spawn MCP process
    │
    ▼
STDIO
```

Config:

```json
{
  "transport_type": "stdio",
  "auth_type": "environment",
  "env_vars": [
    {
      "name": "GITHUB_PERSONAL_ACCESS_TOKEN",
      "required": true,
      "secret": true
    }
  ]
}
```

---

# 10. HTTP + Bearer Authentication

```text
User Credential
      │
      ▼
Fernet Vault
      │
      ▼
Decrypt during connection
      │
      ▼
Authorization: Bearer <token>
      │
      ▼
HTTP MCP Endpoint
      │
      ▼
initialize
      │
      ▼
tools/list
```

Example:

```json
{
  "transport_type": "streamable_http",
  "endpoint": "https://example.com/mcp",
  "auth_type": "bearer"
}
```

---

# 11. HTTP + API Key

API key placement must be discovered from server documentation/configuration.

Possible forms:

```text
Authorization: Bearer <key>
X-API-Key: <key>
Api-Key: <key>
Custom header
Query parameter (only if explicitly supported)
```

Prefer headers over query parameters when supported.

Config should be dynamic:

```json
{
  "transport_type": "streamable_http",
  "auth_type": "api_key",
  "auth_schema": {
    "fields": [
      {
        "name": "api_key",
        "type": "secret",
        "required": true,
        "location": "header"
      }
    ]
  }
}
```

---

# 12. OAuth2 / OAuth2 + PKCE

For remote MCP servers requiring OAuth:

```text
                USER
                  │
                  ▼
             Connect MCP
                  │
                  ▼
            OAuth Discovery
                  │
                  ▼
          Authorization Server
                  │
                  ▼
            User Consent
                  │
                  ▼
             Auth Callback
                  │
                  ▼
             Access Token
                  │
                  ▼
              MCP Client
                  │
                  ▼
        Authorization: Bearer
                  │
                  ▼
             MCP /mcp
                  │
                  ▼
             tools/list
```

OAuth configuration should be discovered rather than hardcoded per vendor.

---

# 13. Authentication Detection

Do not depend only on environment-variable regex.

Use evidence in this order:

```text
README / Documentation
        │
        ▼
.env.example / sample config
        │
        ▼
package.json / pyproject.toml
        │
        ▼
Source Code
        │
        ▼
CLI --help
        │
        ▼
Config Schema
        │
        ▼
Regex fallback
```

Example source evidence:

```text
process.env.GITHUB_PERSONAL_ACCESS_TOKEN
```

should produce:

```json
{
  "name": "GITHUB_PERSONAL_ACCESS_TOKEN",
  "type": "secret",
  "required": true
}
```

But avoid building a giant vendor-specific regex list.

---

# 14. Transport Detection Algorithm

```text
START
  │
  ▼
Is source a remote MCP URL?
  │
  ├── YES
  │    │
  │    ▼
  │  Probe endpoint
  │    │
  │    ├── Streamable HTTP → select streamable_http
  │    │
  │    ├── SSE → select sse
  │    │
  │    └── Unknown → mark unknown
  │
  └── NO
       │
       ▼
   Is GitHub/source repo?
       │
       ▼
   Clone / Download
       │
       ▼
   Resolve subpath
       │
       ▼
   Read README/docs
       │
       ▼
   Scan source code
       │
       ▼
   Inspect package metadata
       │
       ▼
   Detect MCP SDK patterns
       │
       ├── STDIO evidence
       │
       ├── Streamable HTTP evidence
       │
       └── SSE evidence
       │
       ▼
   Confidence scoring
       │
       ▼
   Select highest-confidence transport
       │
       ▼
      END
```

---

# 15. Evidence + Confidence

Do not store only:

```json
{
  "transport_type": "stdio"
}
```

Store evidence:

```json
{
  "transport_type": "stdio",
  "confidence": 0.98,
  "evidence": [
    {
      "source": "README",
      "reason": "Server is started using stdio"
    },
    {
      "source": "source",
      "reason": "StdioServerTransport detected"
    },
    {
      "source": "package.json",
      "reason": "CLI entrypoint detected"
    }
  ]
}
```

Suggested confidence:

```text
0.95 - 1.00  Very strong
0.80 - 0.94  Strong
0.60 - 0.79  Medium
0.40 - 0.59  Weak
< 0.40       Unknown
```

If confidence is low, prefer probing instead of guessing.

---

# 16. Runtime Detection

Supported runtime types:

```text
Node.js
Python
Go
Rust
Docker
Binary
Unknown
```

Detection evidence:

```text
package.json       → Node
pyproject.toml     → Python
requirements.txt   → Python
go.mod             → Go
Cargo.toml         → Rust
Dockerfile         → Docker
binary executable  → Binary
```

Example:

```json
{
  "runtime_type": "python",
  "command": "uv",
  "args": ["run", "server.py"]
}
```

---

# 17. Entrypoint Detection

The analyzer must determine how to start a local MCP server.

Possible methods:

```text
Node:
  npm
  npx
  node

Python:
  uv
  uvx
  python
  python -m

Go:
  compiled binary
  go run

Rust:
  cargo run
  compiled binary

Docker:
  docker run
```

Important:

```text
GitHub repository
       ≠
npm package
```

Before using:

```text
npx -y package-name
```

verify that the package actually exists in the npm registry.

If unpublished:

```text
GitHub repo
    ↓
local build/source
    ↓
local entrypoint
```

Do not blindly use `npx`.

---

# 18. Monorepo / Subpath Handling

Example:

```text
https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem
```

Parse:

```text
owner      = modelcontextprotocol
repo       = servers
branch     = main
subpath    = src/filesystem
```

Flow:

```text
GitHub URL
    │
    ▼
Clone modelcontextprotocol/servers
    │
    ▼
/repo/src/filesystem
    │
    ▼
Analyze only target MCP package
    │
    ▼
Resolve package/entrypoint
    │
    ▼
Set working_directory=/repo/src/filesystem
```

This is critical for:

```text
Filesystem
Git
Fetch
Memory
Sequential Thinking
Time
PostgreSQL
Stripe mcp/
```

---

# 19. Universal Normalized Configuration

All MCP servers should eventually become this kind of configuration:

```json
{
  "source": {
    "type": "github",
    "url": "https://github.com/vendor/project",
    "repo": "vendor/project",
    "branch": "main",
    "subpath": "mcp"
  },

  "transport": {
    "type": "stdio",
    "confidence": 0.98,
    "evidence": []
  },

  "runtime": {
    "type": "node"
  },

  "startup": {
    "command": "node",
    "args": ["dist/index.js"],
    "working_directory": "/repo/mcp"
  },

  "endpoint": null,

  "auth": {
    "type": "environment",
    "schema": {
      "fields": []
    }
  }
}
```

For remote:

```json
{
  "source": {
    "type": "remote",
    "url": "https://example.com/mcp"
  },

  "transport": {
    "type": "streamable_http",
    "confidence": 0.99
  },

  "runtime": null,

  "startup": null,

  "endpoint": "https://example.com/mcp",

  "auth": {
    "type": "bearer"
  }
}
```

---

# 20. Step 1 — Register Server

Step 1 must **not** attempt connection when credentials are missing.

```text
USER
 │
 ▼
Add MCP
 │
 ▼
Analyze
 │
 ▼
Detect:
 ├── source
 ├── subpath
 ├── transport
 ├── runtime
 ├── command
 ├── endpoint
 └── auth schema
 │
 ▼
Create VendorMCPServer
 │
 ▼
201 Created
 │
 ▼
Server = UNCONNECTED
```

For authenticated servers:

```text
credentials not supplied
        │
        ▼
DO NOT CONNECT
        │
        ▼
DO NOT generate connection error
        │
        ▼
Return 201
```

For no-auth servers:

```text
auth_type = none
        │
        ▼
Registration can still remain separate
        │
        ▼
User explicitly tests connection
```

The lifecycle remains strictly two-step.

---

# 21. Step 2 — Test Connection & Discover Tools

```text
User
 │
 ▼
Open MCP Server
 │
 ▼
Click "Test Connection"
 │
 ▼
Generate Credential Form
from auth_schema
 │
 ▼
User enters credentials
 │
 ▼
Fernet Vault
 │
 ▼
Build Runtime Config
 │
 ▼
Select Generic Adapter
 │
 ├── STDIO
 ├── Streamable HTTP
 └── SSE
 │
 ▼
Connect
 │
 ▼
MCP initialize
 │
 ▼
tools/list
 │
 ▼
Save tools
 │
 ▼
Server VERIFIED
 │
 ▼
Tools available to AI Compiler
```

---

# 22. Generic MCP Client Architecture

```text
                 MCPClient
                    │
          ┌─────────┼─────────┐
          │         │         │
          ▼         ▼         ▼
       STDIO      HTTP       SSE
       Adapter   Adapter    Adapter
          │         │         │
          └─────────┼─────────┘
                    ▼
             MCP Protocol
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      initialize()         tools/list
          │                   │
          └─────────┬─────────┘
                    ▼
                MCP Tools
```

There should NOT be:

```text
GitHubClient
StripeClient
XeroClient
OdooClient
SalesforceClient
```

for MCP transport.

Vendor-specific logic belongs in **analysis evidence**, not in the runtime connection layer.

---

# 23. Example Server Matrix

| Server | Source | Transport | Auth | Runtime/Method |
|---|---|---|---|---|
| Filesystem MCP | GitHub subpath | STDIO | None | Local source |
| Git MCP | GitHub subpath | STDIO | None | Local source |
| Fetch MCP | GitHub subpath | STDIO | None | Local source |
| Memory MCP | GitHub subpath | STDIO | None | Local source |
| Sequential Thinking | GitHub subpath | STDIO | None | Local source |
| Time MCP | GitHub subpath | STDIO | None | Local source |
| GitHub MCP | GitHub repo | STDIO | Environment/PAT | Go |
| Playwright MCP | GitHub/npm | STDIO | None | Node |
| Brave Search | GitHub repo | STDIO | Environment | Runtime-dependent |
| PostgreSQL MCP | GitHub subpath | STDIO | CLI/env | Python |
| QuickBooks | GitHub repo | STDIO | Environment | Node/source |
| Stripe | GitHub subpath | STDIO | Environment | Node |
| Xero | GitHub repo | STDIO | Environment/OAuth | Runtime-dependent |
| Salesforce | GitHub repo | STDIO | Environment | Runtime-dependent |
| HubSpot | Remote URL | Streamable HTTP | Bearer/OAuth | Remote |
| Pipedrive | GitHub repo | STDIO | Environment | Runtime-dependent |
| Shopify Dev MCP | Remote/local docs | Streamable HTTP or local | None/OAuth depending deployment | Remote/local |
| WooCommerce | GitHub repo | STDIO | Environment | Runtime-dependent |
| Odoo | GitHub repo | STDIO | Environment | Python |
| ERPNext | GitHub repo | STDIO | Environment | Python |
| Google Ads | GitHub repo | STDIO | Environment | Runtime-dependent |
| Meta Ads | Remote URL | Streamable HTTP | Bearer | Remote |
| GA4 | GitHub repo | STDIO | Environment | Runtime-dependent |

The matrix is illustrative; the analyzer remains the source of truth.

---

# 24. Database Model

## VendorMCPServer

```text
id
name

source_type
source_url
source_repo
source_branch
source_subpath

ownership_type

transport_type
transport_confidence
transport_evidence

runtime_type

command
args
working_directory

endpoint

auth_type
auth_schema

status

analysis_metadata

created_at
updated_at
```

## MCPCredential

```text
id
mcp_server_id
credential_type
encrypted_value
created_at
updated_at
```

## MCPTool

```text
id
mcp_server_id
name
description
input_schema
output_schema
created_at
updated_at
```

---

# 25. Dynamic Credential UI

Frontend should receive:

```json
{
  "auth_type": "environment",
  "fields": [
    {
      "name": "API_KEY",
      "label": "API Key",
      "type": "secret",
      "required": true
    },
    {
      "name": "API_ENDPOINT",
      "label": "API Endpoint",
      "type": "text",
      "required": false
    }
  ]
}
```

Then automatically render:

```text
┌─────────────────────────────────┐
│ Connect MCP Server              │
├─────────────────────────────────┤
│ API Key                         │
│ [****************************]  │
│                                 │
│ API Endpoint                    │
│ [https://....................]  │
│                                 │
│              [Test Connection]  │
└─────────────────────────────────┘
```

No:

```text
if server == "stripe":
    show Stripe form

if server == "github":
    show GitHub form
```

---

# 26. Error Handling

## Invalid/private GitHub repository

```text
Clone failed
   │
   ▼
Tarball fallback
   │
   ▼
Failed
   │
   ▼
404/400
"GitHub repository not found or private"
```

Do NOT:

```text
run dummy backend/server.py
```

Do NOT create misleading connection errors during registration.

---

## Missing Credentials

```text
Register
   │
   ▼
Auth required
   │
   ▼
Credentials missing
   │
   ▼
Save server successfully
   │
   ▼
201 Created
   │
   ▼
Status = UNCONNECTED
```

This is not an error.

---

## Remote 401/403

```text
HTTP endpoint responds 401
        │
        ├── Transport may still be known
        │
        ▼
transport = streamable_http
auth = required
        │
        ▼
Ask for credentials
```

Do not classify:

```text
401 = unknown transport
```

---

# 27. Security

GitHub/source repositories contain arbitrary code.

Never directly execute arbitrary repository code on the backend host.

Use:

```text
GitHub repo
    │
    ▼
Isolated sandbox/container
    │
    ├── clone
    ├── inspect
    ├── install/build
    └── run MCP
```

Recommended isolation:

```text
No privileged host access
Restricted filesystem
Restricted network where possible
Resource limits
Process timeout
Memory limits
Temporary workspace
Credential injection only at runtime
```

Credentials must never be written into repository files.

---

# 28. Final Architecture

```text
                         ┌──────────────────────┐
                         │      ADD MCP SERVER  │
                         └──────────┬───────────┘
                                    │
                  ┌─────────────────┴─────────────────┐
                  │                                   │
                  ▼                                   ▼
          ┌───────────────┐                  ┌────────────────┐
          │ Remote URL    │                  │ GitHub / Repo  │
          └───────┬───────┘                  └───────┬────────┘
                  │                                  │
                  │                                  ▼
                  │                         Clone / Tarball
                  │                                  │
                  └────────────────┬─────────────────┘
                                   ▼
                         ┌────────────────────┐
                         │   REPO ANALYZER    │
                         ├────────────────────┤
                         │ Source             │
                         │ Subpath            │
                         │ Transport          │
                         │ Runtime            │
                         │ Entrypoint         │
                         │ Authentication     │
                         │ Credentials schema │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ NORMALIZED CONFIG  │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ STEP 1 REGISTER    │
                         │ No connection yet  │
                         └─────────┬──────────┘
                                   │
                              201 Created
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ MCP SERVER SAVED   │
                         │ UNCONNECTED        │
                         └─────────┬──────────┘
                                   │
                          User: Test Connection
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ CREDENTIAL FORM    │
                         │ Dynamic from schema│
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │   FERNET VAULT     │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │   MCP CLIENT       │
                         └─────────┬──────────┘
                                   │
                 ┌─────────────────┼─────────────────┐
                 │                 │                 │
                 ▼                 ▼                 ▼
              STDIO        STREAMABLE HTTP         SSE
                 │                 │                 │
                 └─────────────────┼─────────────────┘
                                   ▼
                              initialize()
                                   │
                                   ▼
                               tools/list
                                   │
                                   ▼
                              Save Tools
                                   │
                                   ▼
                             ┌──────────┐
                             │ VERIFIED │
                             └────┬─────┘
                                  │
                                  ▼
                           AI COMPILER
```

---

# 29. Core Design Rules

```text
RULE 1
Source type != Transport type

RULE 2
Ownership != Connection method

RULE 3
Transport != Authentication

RULE 4
GitHub URL != MCP endpoint

RULE 5
Remote URL != Git repository

RULE 6
Analyze first, connect second

RULE 7
Missing credentials during registration is NOT an error

RULE 8
Use dynamic auth_schema instead of vendor-specific UI

RULE 9
Use generic transport adapters

RULE 10
Use evidence + confidence instead of blind regex

RULE 11
Verify npm package existence before npx

RULE 12
Support GitHub monorepo subpaths as first-class metadata

RULE 13
Probe ambiguous remote endpoints instead of guessing

RULE 14
Never execute arbitrary MCP repository code directly on host

RULE 15
Vendor-specific code should not exist in the MCP connection layer
```

---

# 30. One-Line Mental Model

```text
ADD SOURCE
   ↓
ANALYZE
   ↓
DETECT TRANSPORT + RUNTIME + AUTH
   ↓
NORMALIZE
   ↓
REGISTER
   ↓
USER PROVIDES CREDENTIALS
   ↓
CONNECT USING GENERIC ADAPTER
   ↓
initialize()
   ↓
tools/list
   ↓
VERIFIED MCP
```

This is the target architecture for a truly universal MCP Marketplace/Connection Engine.
