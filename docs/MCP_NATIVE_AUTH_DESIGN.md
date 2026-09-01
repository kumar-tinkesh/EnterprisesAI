# Native MCP Server Authentication — Design

> Status: **Implemented** · Modules: `apps/backend/vendor_resources/services/`
> (`mcp_detect.py`, `mcp_auth.py`, `mcp_client.py`, `mcp_service.py`)

## 1. Goal

Connect to **any** MCP server natively, with **zero provider-specific code** —
no hardcoded hostnames, no "if url contains gmail" branches. Everything is
derived from what the server itself advertises via open standards, or from
credentials the vendor/tenant supplies.

Supported server classes:

| Server class | Auth requirement | Native handling |
|---|---|---|
| **Local MCP server** (stdio command) | Usually none / local config | Process spawned with credentials as env vars + `{field}` substitution in the command |
| **Public MCP server** (no auth) | Nothing | Unauthenticated `initialize` probe succeeds → `auth_type=none` |
| **API-based MCP** | API key / token | RFC 6750 challenge parsing → `api_key` / `bearer` / `basic` header injection |
| **OAuth-protected MCP** | Client ID + Client Secret + OAuth flow | RFC 9728 → RFC 8414 metadata discovery → native `client_credentials` / `refresh_token` grants, optional RFC 7591 dynamic client registration |
| **Enterprise / private MCP** | OAuth, API key, JWT, … | Same engine — the challenge/metadata decides; JWTs are passed through as Bearer tokens; unknown schemes degrade to raw header passthrough |

## 2. Architecture

```
                     ┌────────────────────────────────────────────────┐
 registration        │ mcp_detect.detect_mcp_server(url)              │
      ──────────────►│  • probe <url>, /mcp, /sse (initialize)        │
                     │  • 200 → none                                  │
                     │  • 401/403 → RFC 6750 challenge classify       │
                     │  • RFC 9728 protected-resource metadata        │
                     │  • RFC 8414 / OIDC authorization-server meta   │
                     └──────────────┬─────────────────────────────────┘
                                    │ auth_config (persisted on
                                    │ vendor_mcp_servers.auth_config)
                                    ▼
                     ┌────────────────────────────────────────────────┐
 connect             │ mcp_auth.resolve_auth(db, server, credentials) │
      ──────────────►│  • merge stored (encrypted) + request creds    │
                     │  • none/api_key/basic/bearer → headers         │
                     │  • oauth2 → token engine (below)               │
                     └──────────────┬─────────────────────────────────┘
                                    │ headers
                                    ▼
                     ┌────────────────────────────────────────────────┐
                     │ mcp_client.connect_mcp_server(...)             │
                     │  • streamable_http → sse fallback, or stdio    │
                     │  • MCP handshake + tools/list discovery        │
                     └────────────────────────────────────────────────┘
```

### 2.1 Detection — `mcp_detect.py` (no hardcoding)

The old `_KNOWN_PROVIDER_HINTS` URL-pattern table (gmail/github/slack/…) was
**removed**. Classification now comes only from:

1. **RFC 6750 `WWW-Authenticate` challenges**
   - `Basic` → `basic`
   - `Bearer` → `bearer` (upgraded to `oauth2` only if OAuth metadata is found,
     because a Bearer challenge may also guard a static token/JWT)
   - custom scheme (`ApiKey`, `Token`, …) → `api_key`
2. **RFC 9728 protected-resource metadata**
   - from `resource_metadata="…"` in the Bearer challenge, or
     `/.well-known/oauth-protected-resource`
   - yields `authorization_servers[]` and `scopes_supported`
3. **RFC 8414 / OIDC authorization-server metadata**
   - `/.well-known/oauth-authorization-server`, then
     `/.well-known/openid-configuration` on each advertised issuer
   - yields `token_endpoint`, `registration_endpoint`, `scopes_supported`,
     `grant_types_supported`
4. **Fallback**: if the resource never answered, the base URL is probed as an
   authorization server directly (proxy-swallowed-challenge case).

If nothing answers, the server is reported `unknown`/unreachable with the
probe evidence in `hints` — it is **never** guessed from the URL.

The detection result embeds the discovered endpoints in an `oauth` block,
which is persisted into `vendor_mcp_servers.auth_config["oauth"]` so the
runtime never needs to re-probe:

```json
{
  "auth_type": "oauth2",
  "credential_fields": [{"name": "client_id"}],
  "oauth": {
    "authorization_server": "https://sso.example.com",
    "token_endpoint": "https://sso.example.com/oauth/token",
    "registration_endpoint": "https://sso.example.com/oauth/register",
    "scopes_supported": ["mcp:tools"],
    "grant_types_supported": ["client_credentials", "refresh_token"]
  }
}
```

### 2.2 Credential resolution — `mcp_auth.py`

`resolve_auth(db, server_id=…, server_url=…, auth_config=…, credentials=…,
tenant_id=…)` returns `{headers, credentials, auth_type, token_source}`:

| auth_type | Result |
|---|---|
| `none` / `env` | no headers (stdio creds go in via env vars at spawn time) |
| `api_key` | `X-API-Key: <key>` (or `header_name` override) |
| `basic` | `Authorization: Basic base64(user:pass)` |
| `bearer` | `Authorization: Bearer <access_token \| token \| bearer_token \| jwt \| api_key>` |
| `oauth2` | token engine, below |
| `unknown` | raw auth-header passthrough (legacy clients) |

**OAuth2 token engine** (all endpoints from the persisted `oauth` metadata):

1. **Cache** — in-memory, keyed `(server_id, tenant_id)`; entries are reused
   until `expires_in − 60 s` (no HTTP on warm calls).
2. **`refresh_token` grant** (RFC 6749 §6) — used when a refresh token is
   stored; rotated refresh tokens returned by the AS are **re-encrypted and
   persisted automatically**.
3. **`client_credentials` grant** (RFC 6749 §4.4) — `client_id` +
   `client_secret` authenticated via HTTP Basic; `scope` from the request or
   the advertised `scopes_supported`.
4. **Dynamic client registration** (RFC 7591) — when no `client_id` exists
   but the AS advertises a `registration_endpoint`; the registered client is
   persisted and used for `client_credentials`.
5. **Passthrough** — a pre-obtained `access_token` (e.g. a long-lived JWT)
   is sent as-is.
6. Otherwise → `McpAuthError` (mapped to HTTP 400 by the connect endpoint).

### 2.3 Credential storage — `vendor_mcp_credentials`

New table (migration `a7b8c9d0e1f2`):

| column | type | notes |
|---|---|---|
| `id` | String(36) PK | |
| `server_id` | String(36) FK → `vendor_mcp_servers.id` ON DELETE CASCADE | |
| `tenant_id` | String(36) NULL | `NULL` = vendor-level credentials; a per-tenant row overrides the fallback |
| `encrypted_credentials` | Text | Fernet-encrypted JSON blob |
| `created_at` / `updated_at` | DateTime(tz) | `TimestampMixin` |

- Payload fields are whatever the auth type needs: `api_key`, `username`/
  `password`, `client_id`/`client_secret`/`refresh_token`, `access_token`, …
- Encryption: Fernet with a PBKDF2-HMAC-SHA256 key derived from
  `MCP_CREDENTIALS_SECRET` (falls back to the persisted JWT private key),
  salt `mcp_credentials_salt` — the **same scheme and salt as
  `apps/auth/src/api/v1/mcp/credentials.py`**, so both modules interoperate.
- Request-supplied credentials always override stored ones for a given call;
  stored values not overridden are still merged in.
- Server deletion cascades: grants, credential rows, and cached tokens.

### 2.4 Connection — `mcp_client.py`

`connect_mcp_server(url, credentials, transport, auth_type, timeout,
auth_headers)` — `auth_headers` (from `resolve_auth`) takes precedence over
the legacy in-place header building. Transports unchanged: streamable HTTP →
SSE fallback for http(s); stdio command for anything else (credentials
injected as upper-cased env vars + `{field}` substitution).

## 3. API surface changes

- `POST /mcp/detect` — response gains `oauth` (discovered metadata block).
- `POST /mcp` — supplied `credentials` are now **persisted encrypted** (they
  were used once and discarded before).
- `POST /mcp/{id}/connect` — resolves auth natively (stored + request
  credentials → OAuth2 engine); `400` on unresolvable credentials, `502` on
  connection failure; rotated OAuth tokens are committed.

## 4. Security notes

- Client secrets / refresh tokens are **never** returned by any API; they are
  stored only Fernet-encrypted and decrypted in-process at connect time.
- Token cache is per-process and expires with the token (−60 s margin).
- Leeway between services is not required for OAuth2: tokens are fetched
  against the discovered `token_endpoint` at connect time.
- The OAuth **authorization-code + PKCE** browser flow (end-user consent) is
  out of scope for the backend engine; machine flows (`client_credentials`,
  `refresh_token`) and passthrough tokens cover server-side integration. A
  future phase can add a consent-flow endpoint using the same persisted
  metadata.

## 5. Test coverage

`apps/backend/vendor_resources/tests/` (all network mocked via
`httpx.MockTransport`):

- `test_mcp_detect.py` — open server, Basic challenge, custom-scheme →
  api_key, Bearer without metadata → bearer, full RFC 9728 → RFC 8414
  discovery → oauth2 (+ `resource_metadata` challenge parameter), unreachable
  → unknown (unknown host stays unknown — no URL guessing).
- `test_mcp_auth.py` — header builders per type, encryption round-trip,
  encrypted persistence + request-override merge, `client_credentials`,
  token caching, `refresh_token` with rotation persistence, dynamic
  registration, passthrough, failure → `McpAuthError`.
- `test_router.py` / `test_mcp_service.py` — CRUD/RBAC/catalog regressions
  with the network stubbed at the service boundary.
