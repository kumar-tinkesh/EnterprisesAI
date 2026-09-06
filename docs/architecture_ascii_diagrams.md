# EnterpriseAI — Current Architecture (As-Built)

> Scope: this document describes ONLY what exists in the repository today, verified by direct
> source inspection. It does not evaluate the design, does not propose changes, and does not
> describe deferred/roadmap work except where the roadmap items are named as such.
>
> Legend used throughout:
> - **[CONFIRMED]** — read directly from source code, cited with `file:line`.
> - **[INFERRED]** — a reasonable conclusion from how confirmed pieces connect, not itself a single line of code.
> - **[UNKNOWN]** — could not be verified from the repository (e.g. behavior of a third-party library internals).
>
> Superseded content notice: an earlier version of this document (Phases 1–3) described an
> `apps/backend/vendor_resources` subsystem built around `vendor_tools`, `tool_embeddings`, an AI
> "compiler" (`compiler.py`), a LangGraph `executor.py`, and a `tool_executor.py`. **None of those
> files exist in the current tree.** The subsystem was replaced by the "Universal MCP Server Add &
> Connection Flow" (registry + detection + generic MCP client), documented below. Where the old
> document's claims are relevant for contrast they are called out explicitly as *removed*.
>
> Update notice (this pass): a prior pass of this document found `catalog_engine.py`'s semantic
> ranking broken (`AttributeError` on nonexistent `.dim`/`.embedding` columns), the frontend's
> `agents/compile`/`agents/run` calls hitting nonexistent routes (404), and no tool-invocation code
> path anywhere. **This pass adds real, working code for the first two** — real embedding columns,
> a hybrid (vector + BM25 + cross-encoder rerank) search primitive, a two-stage tool-selection
> function, an LLM-function-calling argument-filler, and a generic OAuth "Connect via provider" bootstrap
> flow — documented in the new §2.10–§2.12. **The third finding still holds without qualification: there
> is still no code path anywhere in the repository that invokes a discovered MCP tool.** Everything
> added in this pass is selection/argument-filling only, one step short of that boundary by design —
> see §2.11's explicit statement of this and §3.6 (unchanged).

---

## 0. Repository shape

**[CONFIRMED]** — uv monorepo, single dependency manifest at the repo root.

```
EnterpriseAI/                         (pyproject.toml = uv project root, single venv)
├── pyproject.toml, uv.lock           deps incl. fastapi, sqlalchemy[asyncio], alembic,
│                                      pwdlib[argon2], pyjwt[crypto], litellm, mcp>=2.1.1,
│                                      PyGithub, structlog, rank-bm25, fastembed
├── alembic.ini                       points at apps/auth/alembic (single migration chain)
├── data/auth.db                      shared SQLite DB (docker: /data/auth.db volume)
├── scripts/
│   └── seed_admin.py                  create/reset the platform admin (VendorUser) — no self-signup UI exists for this role
├── apps/
│   ├── auth/                          Auth Service  (FastAPI, port 8001)
│   │   ├── src/main.py                entrypoint — ALSO mounts vendor_resources.router
│   │   ├── src/config.py              global Settings (pydantic-settings), imported everywhere
│   │   ├── src/core/                  security.py (JWT/JWKS/Argon2id), oidc.py, roles.py, audit.py
│   │   ├── src/db/                    base.py (Base/TimestampMixin), session.py, migrations.py, rls.py
│   │   ├── src/models/                User, VendorUser, Tenant, Workspace, RefreshToken, AuditEvent, …
│   │   └── src/api/v1/                auth/, sso/, tenant/, vendor/, dashboard/, mcp/ (legacy, see §2.6)
│   ├── llm_gateway/                    LLM Gateway (LiteLLM wrapper; not an MCP component)
│   │   └── config.py                   ProviderConfig.is_azure — Azure OpenAI routing (deployment-name
│   │                                    prefix + api_version), see §1.2
│   └── backend/                        Backend Service (FastAPI, port 8002)
│       ├── main.py                     entrypoint — mounts vendor_resources.router (again)
│       ├── config.py                   BackendSettings (API prefix, CORS, BACKEND_PUBLIC_URL for OAuth callback)
│       └── vendor_resources/           the Universal MCP Server Engine (§2)
│           ├── models.py               VendorMCPServer, VendorMCPCredential, TenantResourceGrant, MCPTool
│           │                            (VendorMCPServer + MCPTool now also carry embedding/embedding_model/dim)
│           ├── schemas.py               Pydantic request/response contracts
│           ├── router.py                FastAPI routes, mounted at /api/v1/vendor/resources
│           ├── services/
│           │   ├── repo_analyzer.py     source analysis → NormalizedMCPConfig (now caches per-URL, §2.4)
│           │   ├── mcp_detect.py        live HTTP probing → transport/auth classification
│           │   ├── mcp_client.py        MCPClient — stdio/streamable_http/sse adapters (official `mcp` SDK)
│           │   ├── mcp_auth.py          credential vault + OAuth2 token acquisition (+ authorization_code grant, §2.12)
│           │   ├── mcp_service.py       orchestration: register → test-connection → CRUD → grants
│           │   ├── catalog_engine.py     access-filtered catalog + embeddings + two-stage hybrid search (§2.10)
│           │   ├── hybrid_search.py      NEW — vector+BM25+rerank ranking primitive (§2.10)
│           │   ├── tool_call_planner.py  NEW — LLM function-calling argument-filler (§2.11)
│           │   ├── oauth_flow.py         NEW — generic "Connect via provider" OAuth bootstrap (§2.12)
│           │   └── llm_gateway_client.py NEW — shared LLMGateway singleton for the above
│           └── tests/                   pytest suite (isolated SQLite engine, network calls stubbed)
├── docker/                              Dockerfile.auth, Dockerfile.backend, Dockerfile.llm_gateway, entrypoint.sh
├── docker-compose.yml                    services: auth, web, redis, llm-gateway, backend, db(postgres, optional profile)
└── web/                                  Next.js 15 frontend (app/, components/, lib/api.ts, stores/)
```

**[CONFIRMED]** Both `apps/backend/main.py:38` and `apps/auth/src/main.py:31/89-92` import and mount
the *same* `vendor_resources.router` object under the same prefix
(`{BACKEND_API_V1_PREFIX}/vendor/resources`, i.e. `/api/v1/vendor/resources`). This means the MCP
registry API is reachable from **both** the auth service (port 8001) and the backend service (port
8002) against the same shared database — there are two independent FastAPI `app` instances serving
overlapping routes, not a single shared process.

**[CONFIRMED]** There is a second, older, still-mounted MCP CRUD surface at
`apps/auth/src/api/v1/mcp/` (`router.py`, `service.py`, `schemas.py`, `credentials.py`), wired into
`api_router` in `apps/auth/src/api/v1/router.py:11,19` and therefore live at `/api/v1/mcp/*` on the
auth service. See §2.6 for what it actually does and how it differs from — and partially conflicts
with — the `vendor_resources` engine. **[CONFIRMED]** The frontend (`web/lib/api.ts:395-418`) calls
only the `vendor_resources` (`/vendor/resources/mcp*`) endpoints against the backend service; it has
no calls to `/api/v1/mcp/*`.

---

## 1. Current system architecture — layers, modules, services

### 1.1 Auth Service (`apps/auth`) — port 8001

**[CONFIRMED]** Standalone FastAPI service, entrypoint `apps/auth/src/main.py`.

| Layer | File(s) | Responsibility |
|---|---|---|
| Entry | `src/main.py` | `create_app()`, lifespan (`run_migrations()` via `asyncio.to_thread`, fallback `create_db_tables()`), CORS, `/health`, `/.well-known/jwks.json`, mounts `api_router` (prefix `settings.API_V1_PREFIX`) and `vendor_resources_router` (prefix `{BACKEND_API_V1_PREFIX}/vendor/resources`) |
| Config | `src/config.py` | `Settings` (pydantic-settings) — single global instance via `get_settings()`; includes `JWT_PRIVATE_KEY`, `MCP_CREDENTIALS_SECRET` (used by `mcp_auth._fernet()`, §2.5) |
| Security | `src/core/security.py` | RS256 JWT issuance/verification (`decode_token`), Argon2id hashing (via `pwdlib`), JWKS publishing (`get_jwks`) |
| SSO | `src/core/oidc.py` | OIDC/PKCE client flow |
| Roles | `src/core/roles.py` | `Roles` class — string constants `VENDOR_ADMIN`, `TENANT_ADMIN`, `TENANT_USER`, `SOLO_USER` (not an `Enum`) |
| Audit | `src/core/audit.py` | `log_audit_event()`, `get_audit_events()` — reused by both auth and vendor_resources services |
| DB | `src/db/base.py` | `Base` (`DeclarativeBase`), `TimestampMixin` (`created_at`/`updated_at`) — shared by every ORM model in the repo, including `vendor_resources.models` |
| DB | `src/db/session.py` | `get_db()` (FastAPI dependency yielding `AsyncSession`), `create_db_tables()` (fallback schema creation) |
| DB | `src/db/migrations.py` | `run_migrations()` — runs Alembic programmatically (worker thread, since Alembic's `env.py` calls `asyncio.run()`) |
| DB | `src/db/rls.py` | `set_tenant_context()` — sets a Postgres GUC for row-level security; no-ops on SQLite |
| Models | `src/models/*.py` | `User`, `VendorUser`, `Tenant`, `Workspace`, `RefreshToken`, `AuditEvent`, `SSOConfig`, … |
| API deps | `src/api/deps.py` | `CurrentUser` (Pydantic model), `get_current_user()` (decodes bearer JWT, loads `User`/`VendorUser` row, sets RLS tenant context), `require_roles(*roles)` |
| API routers | `src/api/v1/{auth,sso,tenant,vendor,dashboard,mcp}/` | mounted by `src/api/v1/router.py` |

#### 1.1.1 Auth Service — endpoints (all under `settings.API_V1_PREFIX`, i.e. `/api/v1`)

**[CONFIRMED]** Six sub-routers, aggregated by `src/api/v1/router.py`:

| Router (prefix) | Method + Path | Auth dependency | Notes |
|---|---|---|---|
| `auth` (`/auth`) | `POST /signup` | none | `auth.service.signup` |
| | `POST /login` | none | `service.login` — issues JWT pair |
| | `POST /refresh` | none (refresh token in body) | `service.refresh_tokens` — rotates refresh token |
| | `POST /logout` | none (revokes by refresh token) | `service.logout` |
| | `GET /me` | `Depends(get_current_user)` | returns `CurrentUser` + SSO provider info |
| | `GET /audit-logs` | `Depends(get_current_user)` | `core.audit.get_audit_events`, tenant-scoped unless `vendor_admin` |
| `sso` (`/sso`) | `GET /initiate` | none | `sso_service.initiate` → `oidc.generate_state/pkce_pair/get_discovery/build_authorization_url` |
| | `GET /callback` | none | `sso_service.handle_callback` → `oidc.exchange_code/verify_id_token`; any exception → 400 |
| `tenant` (`/tenant`) | `GET /stats`, `GET/POST /members`, `PATCH/DELETE /members/{id}` | `require_roles(TENANT_ADMIN)` on every route | member CRUD scoped to caller's tenant |
| `vendor` (`/vendor`) | `GET /stats`, `GET/POST /tenants`, `PATCH/DELETE /tenants/{id}` | `require_roles(VENDOR_ADMIN)` on every route | platform-wide tenant CRUD |
| `dashboard` (`/dashboard`) | `GET /vendor` \| `/tenant` \| `/user` \| `/workspace` | role-gated per path (`VENDOR_ADMIN`/`TENANT_ADMIN`/`TENANT_USER`+`SOLO_USER`/all three) | **[CONFIRMED]** static `DashboardResponse(dashboard, role, message)` — no DB access, no-op endpoints |
| `mcp` (`/mcp`, legacy) | see §2.9 | mixed | `McpServerService` / `McpCredentialManager`, operates on `vendor_resources` tables |

**[CONFIRMED — signature mismatch]** `apps/auth/src/api/v1/mcp/service.py` (`McpServerService`/
`McpCredentialManager`) calls `log_audit_event(self.db, user_id=..., event_type=..., details={...})`
(e.g. `service.py:63-68`), but `core.audit.log_audit_event`'s actual signature (`audit.py:11-21`) is
`log_audit_event(db, *, action, user_id=None, tenant_id=None, resource="", detail=None,
ip_address=None, user_agent=None)` — no `event_type`/`details` keyword parameters exist. This is a
confirmed textual mismatch between caller and callee; **[UNKNOWN]** whether this actually raises at
runtime (not executed to confirm), but as written every audit-logging call in the legacy MCP router
would raise `TypeError: log_audit_event() got an unexpected keyword argument 'event_type'`.

#### 1.1.2 Auth Service — data model

**[CONFIRMED]** All tables share one `Base`/`TimestampMixin` (`src/db/base.py`), including the
`vendor_resources` tables (§2):

| Model | Table | Key columns | FKs / relationships |
|---|---|---|---|
| `VendorUser` | `vendor_users` | id, email (unique), hashed_password, full_name, is_active, role=`vendor_admin` | `tenants` (back_populates) |
| `Tenant` | `tenants` | id, name, slug (unique), status, is_personal, vendor_user_id | FK → `vendor_users.id` SET NULL; `workspaces` cascade |
| `User` | `users` | id, tenant_id, email (unique), hashed_password (nullable), full_name, is_active, role, auth_provider, oidc_sub | FK → `tenants.id` CASCADE; `memberships` cascade |
| `Workspace` | `workspaces` | id, tenant_id, name, slug, status; unique(tenant_id, slug) | FK → `tenants.id` CASCADE |
| `WorkspaceMember` | `workspace_members` | id, workspace_id, user_id, role; unique(workspace_id, user_id) | FK → `workspaces.id` CASCADE, `users.id` CASCADE |
| `RefreshToken` | `refresh_tokens` | id, user_id (no FK — polymorphic across `User`/`VendorUser`), token_hash (unique), expires_at, revoked, replaced_by, user_agent | none |
| `AuditEvent` | `audit_events` | id, user_id, tenant_id, action, resource, detail, ip_address, user_agent; indexes on (user_id, action) and (tenant_id, created_at) | none |

`models/__init__.py` imports every model so Alembic autogenerate / `Base.metadata.create_all` sees them all.

#### 1.1.3 Auth Service — security / OIDC internals

**[CONFIRMED]** `core/security.py`:
- `hash_password`/`verify_password` wrap a module-level `_password_hash = PasswordHash.recommended()` (Argon2id, via `pwdlib`).
- Keys: `_ensure_keys(settings)` prefers `settings.JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` env values, else reads `apps/auth/.keys/{private,public}_key.pem`, else generates a fresh RSA-2048 keypair (`_generate_keypair()`, PKCS8, file mode `0600`).
- `create_token(sub, tid, wid, role, token_type="access", expires_minutes=None)` → builds a claims dict → `_load_private_key(settings)` → `jwt.encode(..., headers={"kid": _key_id(public_pem)})`. Called by `create_token_pair(sub, tid, wid, role)` to mint both access and refresh tokens.
- `decode_token(token, expected_type=None)` → `get_keypair()` → `jwt.decode(token, public_pem, algorithms=["RS256"], issuer=settings.JWT_ISSUER, audience=settings.JWT_AUDIENCE, leeway=settings.JWT_LEEWAY_SECONDS, options={"require": [...]})`, then checks `claims["type"] == expected_type`.
- `get_jwks()` → `get_keypair()` → RSA public numbers → base64url `n`/`e` fields, `kid` from `_key_id()`.

**[CONFIRMED]** `core/oidc.py`: `DISCOVERY_CACHE` (module-level dict) caches `get_discovery(issuer_url)` results. `sso_service.initiate()` → `generate_state()` + `pkce_pair()` + `get_discovery()` + `build_authorization_url(state=, code_challenge=)`. `sso_service.handle_callback()` → `exchange_code(code, code_verifier)` → `verify_id_token(id_token, session, discovery)` (matches `kid` against the provider's JWKS, then `jwt.decode` using `RSAAlgorithm.from_jwk`).

#### 1.1.4 Auth Service — DB layer

**[CONFIRMED]** `db/session.py`: `create_async_engine(settings.DATABASE_URL, echo=DB_ECHO[, poolclass=NullPool if sqlite+:memory:])`; `SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)`. `get_db()` is `async with SessionLocal() as session: yield session`, used everywhere as `Depends(get_db)`.

**[CONFIRMED]** `db/rls.py`: `is_supported(url)` returns `True` only for a `postgresql`/`postgres` scheme; `set_tenant_context(session, tenant_id)` issues `SET LOCAL "app.current_tenant" = :tid` only when `is_supported` — a true no-op on SQLite. Called from `api/deps.get_current_user()` for tenant-table `User` rows only (not `VendorUser`, which has no tenant).

**[CONFIRMED]** `db/migrations.py: run_migrations()` builds an in-memory Alembic `Config` (`script_location = apps/auth/alembic`, `sqlalchemy.url = get_settings().DATABASE_URL`), then `command.upgrade(cfg, "head")` — the function both services' lifespans call via `asyncio.to_thread`.

### 1.2 LLM Gateway (`apps/llm_gateway`)

**[CONFIRMED]** Provider-agnostic completion/embedding layer over LiteLLM. It is **not part of the MCP
engine** — no file under `apps/llm_gateway` imports the `mcp` package or references MCP transports.
Structurally it is a fully independent, separately runnable FastAPI service (`api.py`, own Dockerfile,
own port 4000 in `docker-compose.yml`), but the only place(s) it is reused elsewhere in the repo are
under `apps/backend/vendor_resources/services/`: `catalog_engine.embed_text()` (embeddings, §2.10) and
`tool_call_planner.plan_tool_call()` (chat completions, §2.11) — both **[CONFIRMED — updated this
pass]** now go through one shared `LLMGateway.from_env()` singleton
(`llm_gateway_client.get_gateway()`, `@lru_cache`) rather than each constructing its own (avoiding a
second set of provider HTTP clients); still in-process class import, not an HTTP call to the
port-4000 service.

| File | Contents |
|---|---|
| `types.py` | `Role(str, Enum)` — **only** `SYSTEM`/`USER` (no `ASSISTANT`/`TOOL` member exists); `Message`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `CompletionRequest`, `CompletionResponse`, `StreamChunk`, `EmbeddingResponse` dataclasses; `extract_think_block()` (regex `<think>...</think>` splitter) and `ReasoningStreamParser` (stateful streaming splitter for the same tags). |
| `exceptions.py` | `LLMGatewayError(Exception)` base (`message, provider, model, status_code, retryable=False`) → `ProviderNotConfiguredError`, `ProviderAPIError` → `RateLimitError` (forces `retryable=True` in its own `__init__`), `AuthenticationError`, `ModelNotFoundError`, `TokenLimitExceededError`, `ContentFilterError`. |
| `config.py` | `ProviderConfig` (frozen dataclass: `api_key, base_url, default_model, max_retries=3, timeout_seconds=60, organization, api_version, default_embedding_model`, **+ `azure_chat_deployment`, `azure_embedding_deployment`, and an `is_azure` property** — see below) and `GatewaySettings` (frozen dataclass: `openai/groq/gemini: ProviderConfig`, `default_provider="openai"`, `embedding_provider="gemini"`, `enable_cache=False`, `cache_ttl_seconds=3600`), built by `GatewaySettings.from_env()` reading `OPENAI_*`/`GROQ_*`/`GEMINI_*`/`LLM_GATEWAY_*`/`AZURE_OPENAI_*` env vars (`GROQ_BASE_URL`/`GEMINI_BASE_URL` default to their respective OpenAI-compatible endpoints). |
| `providers/base.py` | `BaseLLMClient(abc.ABC)` — abstract `complete`, `stream`, `embed`, `list_models`; concrete `close()` (no-op default), `_resolve_model()`, `is_configured` property. |
| `providers/litellm_client.py` | `LiteLLMClient(BaseLLMClient)` — the **only real implementation**; wraps `litellm.acompletion`/`litellm.aembedding`, builds provider kwargs (`api_key`, conditional `api_base`, `organization`, `timeout`, `num_retries`), and maps `litellm.exceptions.*` → the gateway's own exception hierarchy via `_map_litellm_error()` (`AuthenticationError`→non-retryable, `RateLimitError`→retryable, `NotFoundError`→`ModelNotFoundError`, `ContextWindowExceededError`→`TokenLimitExceededError`, `BadRequestError`→`ContentFilterError` if the message mentions content-filtering else generic, `APIConnectionError`/`Timeout`/`ServiceUnavailableError`→retryable `ProviderAPIError`, anything else→non-retryable). **[CONFIRMED — fixed this pass]** `_litellm_model()`/`_embed_model()` and `_provider_kwargs()` now branch on `ProviderConfig.is_azure` (true when `base_url` contains `azure.com` **and** `api_version` is set): the model is prefixed `azure/{deployment}` instead of `openai/{model}` (Azure routes by *deployment name*, not model name — the plain-OpenAI-shaped request previously 404'd against a real Azure endpoint, verified live), and `api_version` is forwarded as a kwarg (previously read into `ProviderConfig` but never actually passed to `litellm`, a dead config value). |
| `providers/{openai,groq,gemini}_client.py` | Thin subclasses of `LiteLLMClient` that **only override class attributes** — no method overrides exist anywhere in these three files. |

| Class | `PROVIDER_NAME` | `_PREFIX` | `_DEFAULT_EMBED_MODEL` | `EMBEDDINGS_SUPPORTED` | `_PASS_API_BASE` |
|---|---|---|---|---|---|
| `OpenAIClient` | `openai` | `openai/` | `text-embedding-3-small` | `True` | `True` |
| `GroqClient` | `groq` | `groq/` | `""` (none) | `False` | `True` |
| `GeminiClient` | `gemini` | `gemini/` | `gemini-embedding-001` | `True` | `False` (native Gemini base URL, not passed through) |

**[CONFIRMED]** `gateway.py: LLMGateway`:
- `_FALLBACK_ORDER = {"openai": ["gemini", "groq"], "groq": ["openai", "gemini"], "gemini": ["openai", "groq"]}` (exact, module-level).
- `from_env()` classmethod → `LLMGateway(GatewaySettings.from_env())`; `__init__` calls `_init_clients()`, instantiating whichever of `OpenAIClient`/`GroqClient`/`GeminiClient` has `cfg.is_configured` (non-empty API key), silently skipping the rest.
- `complete(request, *, provider=None, fallback=True)`: builds a try-order via `_build_try_order()` (primary provider, then `_FALLBACK_ORDER[primary]` if `fallback=True`, deduped). **Fallback is conditional on the exception's `retryable` flag** — a non-retryable error (e.g. `AuthenticationError`, `ContentFilterError`) raises immediately without trying the next provider; only `exc.retryable and fallback` continues the loop. Successful responses run `extract_think_block()` on the content before returning. Supports an opt-in in-memory response cache (`enable_cache`, SHA-256 cache key over the full request, TTL via `cache_ttl_seconds`).
- `stream(request, ...)`: identical provider-ordering/fallback semantics to `complete`, wrapping each provider's stream in a fresh `ReasoningStreamParser()`.
- `embed(texts, *, model=None, provider=None)`: **a different fallback rule than `complete`/`stream`** — Groq is unconditionally filtered out of the try-order (`EMBEDDINGS_SUPPORTED=False`), and it falls through to the next provider on **any** `LLMGatewayError`, not just retryable ones (no non-retryable short-circuit, unlike `complete`).
- `list_models(provider=None)`, `close()` (calls each client's `close()` — a no-op for `LiteLLMClient` — and clears the client dict), `configured_providers`/`default_provider` properties.

**[CONFIRMED]** `prompts/registry.py` + `templates.py`: `PromptType(str, Enum)` — 9 members: `AI_DESIGNER`, `GRAPH_PATCHER`, `REACT_AGENT`, `RAG_QUERY_REWRITE`, `RAG_GROUNDED_QA`, `GUARDRAIL_INSPECTOR`, `EVALUATION_JUDGE`, `DOCUMENT_EXTRACTION`, `AGENT_COMPILER`. `PromptRegistry.get_template(prompt_type, provider=None)` checks a (currently empty) `_CUSTOM_OVERRIDES` dict first, else the static `_TEMPLATES` map to a raw string constant in `templates.py`. `format(prompt_type, provider=None, **kwargs)` JSON-serializes dict/list kwargs, calls `str.format(**kwargs)` on the template, re-raising `KeyError` with a friendlier message on a missing variable. `register_override()`/`list_prompts()` complete the API. **[CONFIRMED]** `_CUSTOM_OVERRIDES` has no registration call site anywhere in the repo — it stays empty at runtime. `SYSTEM_AGENT_COMPILER` (the template the now-removed `apps/backend` compiler used to format, §3.6) still exists in `templates.py` but has no caller.

**[CONFIRMED]** `api.py` is a **standalone FastAPI app** (`lifespan` builds a module-level `_gateway = LLMGateway.from_env()` singleton on startup, calls `_gateway.close()` on shutdown). Routes: `GET /health`, `GET /providers`, `GET /prompts`, `POST /v1/prompts/render`, `GET /models`, `POST /v1/chat/completions` (SSE streaming via `_stream_sse()` when `stream=True`), `POST /v1/embeddings`. Maps `ProviderNotConfiguredError`→503, other `LLMGatewayError`→`exc.status_code or 502`. **[CONFIRMED]** No file anywhere in `apps/backend` or `apps/auth` imports `apps.llm_gateway.api`, and no HTTP client call targets the `llm-gateway` container's port 4000 — it runs as a deployed, independently addressable service in `docker-compose.yml`, but nothing in this repo's own code calls it over the network (§1.5).

**[CONFIRMED — test-verified]** `apps/llm_gateway/tests/test_gateway.py` / `test_litellm_routing.py` exercise and confirm: fallback-on-retryable-only for `complete`/`stream`; Groq excluded from `embed()`'s try-order; the opt-in cache; per-provider model-name prefixing; `LiteLLMClient.close()` as a no-op.

### 1.3 Backend Service (`apps/backend`) — port 8002

**[CONFIRMED]** `apps/backend/main.py` — a second FastAPI app. Lifespan runs the *same*
`run_migrations()` used by the auth service (imported from `src.db.migrations`), then falls back to
`create_db_tables()`. It mounts only the `vendor_resources_router`, under the same prefix as the
auth service does. `apps/backend/config.py:BackendSettings` supplies `BACKEND_API_V1_PREFIX` and
`BACKEND_CORS_ORIGINS`.

**`apps/backend/vendor_resources/`** is the Universal MCP Server Engine — the subject of §2.

### 1.4 Frontend (`web/`)

**[CONFIRMED]** Next.js 15 / React 19 app (`package.json`: `@tanstack/react-query` 5.62, `zustand` 5.0,
`zod` 3.24, `react-hook-form`, Tailwind 4, Vitest; pnpm 11.24.0). `next.config.ts`:
`reactStrictMode: true`, `output: "standalone"`, redirects `/` → `/auth`. `providers.tsx` wraps the
app in a `QueryClientProvider` (`retry: 1`, `refetchOnWindowFocus: false`).

**Route tree** (`web/app`):

| Route | Purpose |
|---|---|
| `/auth` | login/signup entry (delegates to `login-form.tsx`/`signup-form.tsx`) |
| `/auth/callback` | OIDC/SSO callback handler |
| `/tenant` | tenant-admin dashboard (member management) |
| `/user` | generic authenticated-user dashboard |
| `/user/agents` | AI agent compiler/runner UI |
| `/vendor` | vendor-admin dashboard (tenant management) |
| `/vendor/tools` | MCP server management UI (largest page, ~979 lines) |

**`web/lib/api.ts`** — two base URLs: `API_URL` (default `http://localhost:8001/api/v1`, the auth
service) and `BACKEND_API_URL` (default `http://localhost:8002/api/v1`, the backend/vendor-resources
service). A shared `request<T>()` helper attaches `Authorization: Bearer <token>`; on a `401` with a
token present it calls `tryRefreshToken()` (POSTs `${API_URL}/auth/refresh` with the stored refresh
token, retries the original request once on success, else logs the store out) — throws
`ApiError(status, detail)` on any non-OK response.

`api` object (→ auth service): `login`, `signup`, `me`, `ssoInitiate`, `ssoCallback`, `getTenantStats`,
`getTenantMembers`, `createTenantMember`, `updateTenantMember`, `deleteTenantMember`, `getVendorStats`,
`getVendorTenants`, `createVendorTenant`, `updateVendorTenant`, `deleteVendorTenant`, `getAuditLogs`,
`getDashboard(role)` — each a thin wrapper matching the endpoint tables in §1.1.1.

`vendorApi` object (→ backend service, path prefix `VR = "/vendor/resources"`): `listMCPServers` (GET
`${VR}/mcp`), `createMCPServer` (POST `${VR}/mcp`), `deleteMCPServer` (DELETE `${VR}/{serverId}` —
note: **not** under `/mcp/`), `embedMCPServer` (POST `${VR}/mcp/{id}/embed`), `connectMCPServer` (POST
`${VR}/mcp/{id}/connect`), `disconnectMCPServer` (POST `${VR}/mcp/{id}/disconnect`), `analyzeRepo`
(POST `${VR}/mcp/analyze-repo`), `grantResource` (POST `${VR}/grants`), `getCatalog` (GET
`${VR}/catalog?q=&top_k=`), `setMCPOAuthConfig` (PATCH `${VR}/mcp/{id}/oauth-config`),
`startMCPOAuthAuthorize` (POST `${VR}/mcp/{id}/oauth/authorize`) — see §2.12 — and, replacing the
formerly-dead `compileAgent`/`runAgent` calls (see the cross-reference note below): `searchCatalogTools`
(GET `${VR}/catalog/tools?q=...`, §2.10) and `planToolCall` (GET `${VR}/catalog/plan-tool-call?q=...`, §2.11).

**`web/stores/auth-store.ts`** — Zustand store with `persist` middleware (localStorage key
`"auth-storage"`), holding `accessToken`/`refreshToken`/`user`; `login(payload)`, `logout()`, `role()`
selector; only `accessToken`/`refreshToken`/`user` are persisted (`partialize`). Read directly by
`api.ts`'s `tryRefreshToken()` via `useAuthStore.getState()`.

**`web/lib/validations.ts`** — `ROLES` const (`vendor_admin`, `tenant_admin`, `tenant_user`,
`solo_user` — comment notes it must match `src/core/roles.py`), Zod `loginSchema`/`signupSchema`,
`dashboardPathForRole(role)` / `roleForDashboard(path)` mapping helpers.

**Key-page API cross-reference** (grepped call sites, confirmed against the router inventories in
§1.1.1/§2):

- `web/app/vendor/tools/page.tsx`: `listMCPServers`, `getVendorTenants` (auth service, for a tenant
  picker), `analyzeRepo`, `createMCPServer`, `deleteMCPServer`, `embedMCPServer`, `connectMCPServer`,
  `disconnectMCPServer`, `grantResource` — every one of these has a matching route in `router.py` (§2).
- **[CONFIRMED — fixed this pass, was dead]** `web/app/user/agents/page.tsx` previously called
  `vendorApi.compileAgent`/`.runAgent` against nonexistent `/agents/compile`/`/agents/run` routes
  (404). It now calls `vendorApi.searchCatalogTools` (`GET /catalog/tools`, §2.10 — "Compile": lists
  matching tools + their `input_schema`) and `vendorApi.planToolCall` (`GET /catalog/plan-tool-call`,
  §2.11 — "Run": additionally has an LLM fill in that schema's arguments from the query text). Both
  routes exist and are wired (`router.py:517-556`, confirmed live in-browser this pass). Neither
  calls the selected tool — see §2.11 and §3.6, unchanged. The `CompiledAgentSpec`/`AgentNode`/
  `AgentEdge`/`CompileAgentRequest`/`RunAgentRequest`/`RunAgentResponse` TS interfaces and their
  backend Pydantic counterparts (`schemas.py:300-351` as of the prior pass) were deleted along with
  this fix — nothing else in the repo referenced them (confirmed by grep before removal).
- `web/app/vendor/page.tsx`, `web/app/tenant/page.tsx`, `web/app/auth/callback/page.tsx`: call only
  `api.*` (auth-service) functions, all matching live routes in §1.1.1.
- `web/app/user/page.tsx` / `web/app/auth/page.tsx`: no direct `api.`/`vendorApi.` calls found in the
  page files themselves (delegate to child components not read for this document) —
  **[UNKNOWN]**, not confirmed absent from the feature, only absent from the page-level file.

### 1.5 Infrastructure

**[CONFIRMED]** `docker-compose.yml` (project `enterpriseai`) defines:

| Service | Build | Ports (host:container) | depends_on | Volumes | Profile |
|---|---|---|---|---|---|
| `auth` | `docker/Dockerfile.auth`, context `.` | `${AUTH_PORT:-8001}:8001` | — | `./data:/data`, `./data/.keys:/app/apps/auth/.keys` | default |
| `web` | `web/Dockerfile`, context `./web`, build-arg `NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1` | `${WEB_PORT:-3001}:${WEB_PORT:-3001}` (**[CONFIRMED — fixed this pass]**; was `:3000` — container `PORT` env now set to match `WEB_PORT`, so Next.js's own startup log prints the correct, browser-reachable port instead of the internal-only `3000`) | `auth` (healthy) | — | default |
| `redis` | image `redis:7-alpine` | `${REDIS_PORT:-6380}:6379` | — | `redisdata:/data` | default |
| `llm-gateway` | `docker/Dockerfile.llm_gateway`, context `.` | `${LLM_GATEWAY_PORT:-4000}:4000` | `redis` (healthy) | `./apps/llm_gateway:/app/apps/llm_gateway` | default |
| `backend` | `docker/Dockerfile.backend`, context `.` | `${BACKEND_PORT:-8002}:8002` | `auth` (healthy) | `./data:/data`, `./data/.keys:/app/apps/auth/.keys` | default |
| `db` | image `postgres:16-alpine` | `${POSTGRES_PORT:-5432}:5432` | — | `pgdata:/var/lib/postgresql/data` | `postgres` (opt-in) |

`auth`/`backend` both default `DATABASE_URL` to `sqlite+aiosqlite:////data/auth.db` and mount the same
`./data` host directory — confirming §0's claim that these are two separate FastAPI processes (two
`AsyncEngine` instances) pointed at one SQLite file, not a shared connection pool. `auth`,
`llm-gateway`, `backend` each load an optional `.env` (`env_file: {required: false}`).

**[CONFIRMED]** `redis` is provisioned but **unused** — no Python file under `apps/` imports a Redis
client (grepped, zero hits in `apps/backend`, `apps/auth`, `apps/llm_gateway`). `llm-gateway` runs
`apps/llm_gateway/api.py` as its own container on port 4000; per §1.2, **[CONFIRMED]** nothing in this
repo's code calls that container's HTTP API — `catalog_engine.py` constructs its own separate
in-process `LLMGateway.from_env()` instance instead. Both facts mean two of the six compose services
(`redis`, and the network surface of `llm-gateway`) are provisioned but not exercised by any code path
found in this repository.

**Dockerfiles:**
- `Dockerfile.auth` / `Dockerfile.llm_gateway`: multi-stage `python:3.12-slim` (`base`→`deps`→`runtime`),
  `uv sync --frozen --no-dev --no-install-project`; auth's runtime stage also copies `alembic.ini`,
  `docker/entrypoint.sh`, creates `/data` + `.keys`, sets `ENV DATABASE_URL=sqlite+aiosqlite:////data/auth.db`,
  `ENTRYPOINT ["entrypoint.sh"]`; llm_gateway's `CMD` runs `uvicorn apps.llm_gateway.api:app --port 4000`
  directly (no migration step — it has no database).
- `Dockerfile.backend`: single-stage `python:3.12-slim`, additionally installs
  `build-essential curl git nodejs npm golang-go` (multi-runtime toolchain — consistent with §2.8's
  stdio servers being spawned in node/go/python) and runs `uv sync --frozen` (no `--no-dev`, unlike the
  other two images). **[CONFIRMED — new this pass]** Also runs
  `uv run python -c "from fastembed.rerank.cross_encoder import TextCrossEncoder; TextCrossEncoder(...)"`
  at build time, baking §2.10's ~80MB ONNX reranker model into the image so the first real query
  doesn't pay for a HuggingFace Hub download and the container works without internet egress at
  runtime. Its entrypoint (written inline via heredoc) runs `alembic upgrade head` (falls
  back to a warning message on failure, does not abort) then `uv run uvicorn main:app --port 8002`.
- `docker/entrypoint.sh` (used by the `auth` container): (1) prints a dev-defaults notice if
  `CSRF_SECRET_KEY` is still `"change-me-in-production"` or `SSO_CLIENT_ID` is empty; (2)
  `alembic upgrade head`; (3) `exec uvicorn src.main:app --app-dir apps/auth --port ${PORT:-8001}`.

**Makefile targets:** `install` (= `install-api` `uv sync --frozen` + `install-web`
`pnpm --dir web install --frozen-lockfile`), `upgrade`/`downgrade`/`stamp`/`revision m=` (Alembic),
`seed-admin email=... password=...` (new this pass — `uv run python scripts/seed_admin.py`; see below),
`api` (`uvicorn src.main:app --app-dir apps/auth --reload --port 8001`), `web` (`pnpm --dir web dev`),
`dev` (= `make -j2 api web`, parallel — **[CONFIRMED] does not start `backend`, `llm-gateway`, or
`redis`**; those are Docker-only via `docker-up`), `test` (= `test-api` `pytest -q` + `test-web`
`pnpm --dir web test`), `docker-up`/`docker-down`, `clean`.

**[CONFIRMED — new this pass]** `scripts/seed_admin.py`: creates or resets the platform admin
(`VendorUser`, `role=vendor_admin`) directly against whatever `DATABASE_URL` is active — there is
no self-signup UI for this role (§1.1.1's `auth` signup path explicitly rejects it for the other two
tenant-scoped roles, and this one simply has no route at all), so a fresh database has no way to log
into the vendor dashboard without it. Idempotent (`--force` to reset an existing account's password);
hashes via the same `pwdlib` Argon2id path used everywhere else (`src.core.security.hash_password`).

---

## 2. MCP architecture

### 2.1 What "MCP server" means in this codebase

**[CONFIRMED]** `VendorMCPServer` (`apps/backend/vendor_resources/models.py:53-206`,
table `vendor_mcp_servers`) is the single registry row type for any MCP server, regardless of
transport or source. Key columns (all on one table — no per-transport subtype tables):

- Identity/lifecycle: `id`, `name`, `description`, `is_global`, `status` (`'UNCONNECTED'` → `'VERIFIED'`), `ownership_type`
- Source: `source_type` (`'github'|'remote'|'local'`), `source_repo`, `source_branch`, `source_subpath`, legacy `source_repo_url`, legacy `server_url`
- Transport: `transport` (canonical value, default `'sse'`), `transport_confidence` (float 0.0–1.0), `transport_evidence` (JSON list of `{source, reason}`)
- Runtime/launch: `runtime_type`, `command`, `args` (JSON list), `working_directory`
- Network: `endpoint`
- Auth: `auth_type` (`'none'|'api_key'|'bearer'|'basic'|'oauth2'|'env'`), `auth_schema` (JSON `{"fields":[...]}`), legacy `auth_config` (JSON blob)
- Legacy: `env_vars` (JSON dict), `bound_tools` (JSON list — tool **names only**, not full schemas)

**[CONFIRMED]** `VendorMCPCredential` (`models.py:213-235`, table `vendor_mcp_credentials`) stores one
Fernet-encrypted JSON blob per `(server_id, tenant_id)` pair, unique index `ix_vmc_server_tenant`;
`tenant_id IS NULL` = vendor-level fallback credentials.

**[CONFIRMED]** `TenantResourceGrant` (`models.py:242-266`, table `tenant_resource_grants`) maps
`(tenant_id, resource_type, resource_id)` → grants a tenant access to a resource; unique index on the
triple. `mcp_service.grant_resource()` (`mcp_service.py:384-444`) restricts `resource_type` to the set
`_GRANTABLE_RESOURCE_TYPES = {"mcp"}` (`mcp_service.py:38`).

**[CONFIRMED — but unused]** `MCPTool` (`models.py:273-298`, table `vendor_mcp_tools`) is a per-tool
row (`mcp_server_id` FK, `name`, `description`, `input_schema`, `output_schema`) added by Alembic
migration `20260903_universal_mcp_server_flow.py`. **Grep across `apps/backend` found zero
references to `MCPTool` outside its own definition in `models.py`** — no service or router imports or
inserts into it. Discovered tool schemas returned by `tools/list` (§2.3) are held only in the
in-memory `result["tools"]` dict returned from `test_mcp_connection()` / `MCPClient.connect()`; the
only thing actually persisted back onto `VendorMCPServer` is `bound_tools` (tool **names**,
`mcp_service.py:314`). The `vendor_mcp_tools` table and `MCPTool` model exist in the schema but are
**dead code / unpopulated** as of this reading.

**[CONFIRMED — stub endpoint]** `POST /mcp/{server_id}/embed` (`router.py:126-140`) looks up the
server, raises 404 if missing, otherwise just commits and returns `204` — it does not compute or
store any embedding. Its docstring ("(Re)compute a server's semantic embedding") does not match its
body.

### 2.2 MCP SDK usage

**[CONFIRMED]** `uv.lock:1336-1339` pins `mcp==2.1.1` (declared as `mcp>=2.1.1` in
`pyproject.toml:21`). The **only** file in the repository that imports the `mcp` package is
`apps/backend/vendor_resources/services/mcp_client.py:35-38`:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
```

No file in the repo constructs an MCP **server** (there is no `mcp.server.*` import anywhere) — this
codebase is exclusively an MCP **client/registry**, not an MCP server host.

### 2.3 Supported transports (client side)

**[CONFIRMED]** Three transports, dispatched by `MCPClient.connect()` (`mcp_client.py:98-118`):

```python
transport = config.get("transport_type") or config.get("transport")
if transport == "stdio":            return await self._stdio_adapter(config)
elif transport == "streamable_http": return await self._streamable_http_adapter(config)
elif transport == "sse":             return await self._sse_adapter(config)
else: raise ValueError(f"Unsupported transport: {transport!r}. Expected 'stdio', 'streamable_http', or 'sse'.")
```

- **stdio** (`_stdio_adapter`, `mcp_client.py:122-166` → `_connect_stdio`, `mcp_client.py:903-1038`):
  spawns a local process via `mcp.client.stdio.stdio_client(StdioServerParameters(command, args, env, cwd))`.
- **streamable_http** (`_streamable_http_adapter`, `mcp_client.py:168-206` → `_handshake`,
  `mcp_client.py:364-384`): `httpx.AsyncClient` + `mcp.client.streamable_http.streamable_http_client(server_url, http_client=http)`.
- **sse** (`_sse_adapter`, `mcp_client.py:208-246` → `_handshake`):
  `mcp.client.sse.sse_client(server_url, headers=..., timeout=...)`.

Both HTTP transports funnel into the shared `_session_details(read_stream, write_stream)`
(`mcp_client.py:345-361`), which does the actual MCP protocol calls:

```python
async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
    init = await session.initialize()
    result = await session.list_tools()
    tools = [_normalize_tool(t) for t in (result.tools or [])]
```

`_normalize_tool()` (`mcp_client.py:335-342`) maps each SDK `Tool` object to
`{"name", "description", "input_schema"}`.

**[CONFIRMED]** A legacy free function `connect_mcp_server()` (`mcp_client.py:392-444`) still exists
for backward compatibility with older callers (`create_mcp_server()` in `mcp_service.py`, and
`router.py:50` imports it directly though — see §2.6 — it is not actually called from `router.py`
after the two-step flow refactor; it auto-detects transport via `_detect_transport()`
(`mcp_client.py:254-263`, a `github.com in url` / `startswith http` / else-stdio heuristic) and tries
`streamable_http` then `sse` in order for non-stdio targets.

### 2.4 Repository / endpoint analysis (`repo_analyzer.py`)

**[CONFIRMED]** `analyze_repo_normalized(repo_url)` (`repo_analyzer.py:531-553`) is the entry point,
dispatching on `detect_source_type(source_url)` (`repo_analyzer.py:510-522` — URL scheme + hostname
`github.com` check → `'github'`, other http(s) → `'remote'`, else `'local'`):

- **github** → `_analyze_github_repo_normalized()` (`repo_analyzer.py:560-646`): parses
  owner/repo/branch/subpath via `_parse_github_url()` (regex, `repo_analyzer.py:178-214`), first tries
  `_fetch_github_raw_manifests()` (`repo_analyzer.py:1072-1137` — unauthenticated
  `raw.githubusercontent.com` GETs for a fixed manifest file list, trying candidate subpaths like
  `f"{repo}-mcp-server"`, `f"{repo}-server"`, `"mcp-server"`, `"server"`, and branches
  `main`/`master`/`HEAD`); if that yields nothing, does a real `git clone --depth 1` into
  `/tmp/repo_analysis/<owner>_<repo>` (10 s timeout) and scans the checkout with `_scan_local_dir()` +
  `_scan_source_files()`, **then deletes the clone in a `finally` block** (`repo_analyzer.py:632-644`)
  after building the config — the clone is not retained for later use by this function (a *separate*
  clone happens again at connect-time in `mcp_client.py`, see §2.7).
- **remote** → `_analyze_remote_http_normalized()` (`repo_analyzer.py:649-712`): delegates to
  `mcp_detect.detect_mcp_server()` (§2.5) for the actual probing, then repackages the result into a
  `NormalizedMCPConfig`.
- **local** → `_analyze_local_path_normalized()` (`repo_analyzer.py:747-770`): scans a filesystem path
  directly.

All three funnel into `_build_normalized_config()` (`repo_analyzer.py:777-859`), which:
1. Runs `_collect_transport_evidence(scanned)` (`repo_analyzer.py:244-380`) — regex scans against
   up to 20 source files (`_SOURCE_CODE_TRANSPORT_PATTERNS`, e.g. `StdioServerTransport` → stdio 0.98,
   `StreamableHTTPServerTransport` → streamable_http 0.98, `SSEServerTransport` → sse 0.98), README
   keyword patterns (`_README_TRANSPORT_PATTERNS`, e.g. `\bstdio\b` → 0.85), manifest-type defaults
   (`package.json` present → stdio 0.70, HTTP framework dep in `package.json`/`pyproject.toml` → +streamable_http
   evidence at 0.65), and Dockerfile/compose presence (docker, weak 0.45–0.55).
2. Picks the highest-confidence transport via `_best_transport()` (`repo_analyzer.py:383-398`), falling
   back to the deterministic legacy heuristic `_infer_transport_and_runtime()`
   (`repo_analyzer.py:927-1069`, manifest-file-driven: `package.json`→node, `pyproject.toml`/`requirements.txt`→python,
   `go.mod`→go, `Cargo.toml`→rust, `Dockerfile`/compose→docker, README URL scan→remote) when confidence < 0.60.
3. Detects auth via `_detect_auth_type()` (`repo_analyzer.py:1226-1280` — README/manifest keyword
   hints: "bearer"→bearer, "api_key"/"x-api-key"→api_key, "oauth"/"client_id"/"credentials.json"→oauth2,
   "basic"→basic, "qr code"/"pairing code"→device_pairing, else env-var-detected→env, else none) and
   extracts required env vars via `_extract_env_vars()` (`repo_analyzer.py:1179-1223`, regex
   `_CREDENTIAL_ENV_KEY_RE` over `.env`/`.env.example`/Dockerfile/compose/README against a suffix
   allowlist `TOKEN|KEY|SECRET|PASSWORD|AUTH|API|ID|URL|PAT|CLIENT_ID|...`, minus a
   `IGNORED_SYSTEM_ENV_VARS` blocklist).
4. Builds `command`/`args` from the raw command string, and `auth_fields` via `_build_auth_fields()`
   (`repo_analyzer.py:451-462`, using a hardcoded `_LABEL_OVERRIDES` dict of ~25 known env-var names →
   human labels, e.g. `GITHUB_TOKEN`→"GitHub Token", `STRIPE_SECRET_KEY`→"Stripe Secret Key" — these
   are UI-label conveniences, not connection-layer branching).

Result: a `NormalizedMCPConfig` dataclass (`repo_analyzer.py:74-163`) with a `.to_dict()` matching the
design doc's §19 schema and a `.to_analyze_repo_response()` for the legacy `AnalyzeRepoResponse`
schema.

**[CONFIRMED — fixed this pass, was a real duplicate-work bug]** `analyze_repo_normalized()` is called
**twice** for the same URL in the normal UI flow — once by the "Analyze" preview
(`POST /mcp/analyze-repo` → `analyze_repo()` → `analyze_repo_normalized()`), and again, independently,
by "Add Server" (`POST /mcp` → `add_mcp_server()` → `analyze_repo_normalized()` again) — and each full
analysis clones/fetches the repo over the network. Verified live: analyzing
`intuit/quickbooks-online-mcp-server` took ~80s the first time; registering the same URL immediately
after (hitting the second, previously-uncached call) took the same ~80s again. Fixed with an in-memory
`_ANALYSIS_CACHE` (`repo_analyzer.py:540-541`, keyed by the stripped URL, 5-minute TTL, returns a
`copy.deepcopy` so a caller mutating the result — `add_mcp_server()` overrides fields from explicit
request params — can't corrupt the cached entry) — verified live to bring the second call down to
effectively instant (`analyzer_cache_hit` log line).

**[CONFIRMED — fixed this pass, real regression found via a live repo]** The `auth_type == "oauth2"`
branch of `_build_normalized_config()` previously **discarded whatever real env vars
`_extract_env_vars()` had actually found** and hardcoded exactly two generic fields, `client_id`/
`client_secret` — verified live against `intuit/quickbooks-online-mcp-server` (a real, published
repo, not a synthetic test case): its actual required vars are
`QUICKBOOKS_CLIENT_ID`/`QUICKBOOKS_CLIENT_SECRET`/`QUICKBOOKS_REALM_ID`/`QUICKBOOKS_REDIRECT_URI`/
`QUICKBOOKS_REFRESH_TOKEN`, none of which were ever shown to the admin, and — because
`mcp_client._connect_stdio()` injects credentials into the spawned process's env using the *field's
own name* as the env var key (§2.7/§3.4) — the generic `client_id`/`client_secret` names it did
collect could never actually reach the process under the names it expects. The two-field override was
removed; the oauth2 branch now builds fields from whatever `_extract_env_vars()` actually found, same
as every other auth type, falling back to the generic `client_id`/`client_secret` pair only when
detection found nothing concrete (verified this fallback still fires correctly for a repo that
mentions "OAuth" without documenting its own env var names). Two related, narrower fixes to
`_extract_env_vars()` in the same pass: (a) it no longer unconditionally drops any `_REFRESH_TOKEN`-
suffixed var (many stdio servers, this one included, expect a pre-obtained refresh token as plain
static config, not something this codebase acquires via any live OAuth flow for them — see §2.12 for
where a live flow *does* now exist, for a different category of server); (b) the credential-suffix
allowlist gained `URI` alongside the existing `URL` (`QUICKBOOKS_REDIRECT_URI` wasn't matched by
either the field-name regex or `_var_field_type()`'s "render as a URL input" check before this).

### 2.5 Detection / probing (`mcp_detect.py`)

**[CONFIRMED]** `detect_mcp_server(server_url, credentials=None, timeout=10.0)`
(`mcp_detect.py:291-533`) is used both directly (via `POST /mcp/detect`, a standalone pre-add probe)
and internally by `repo_analyzer._analyze_remote_http_normalized()`.

Non-`http(s)://` input → immediately classified `transport="stdio"`, `auth_type="env"`,
`transport_confidence=1.0` (`mcp_detect.py:314-342`) — no network call.

For `http(s)://` input, candidates are the URL itself plus `<url>/mcp` and `<url>/sse`
(`_candidate_urls`, `mcp_detect.py:100-107`). For each candidate, `_probe_endpoint()`
(`mcp_detect.py:159-183`) sends an unauthenticated JSON-RPC `initialize` request as a `POST`; if the
response is `404/405/406` it retries as a `GET` with `Accept: text/event-stream`. Classification:

- `POST` → `200`, not SSE content-type → `streamable_http`, confidence `0.99`, `auth_type="none"`.
- `GET` → `200` + `text/event-stream` → `sse`, confidence `0.95`, `auth_type="none"`.
- `POST` → `200` + SSE content-type → `sse`, confidence `0.90`.
- `GET` → `200` without event-stream → `streamable_http` (ambiguous), confidence `0.70`.
- `401`/`403` on `POST` → `streamable_http` (auth required), confidence `0.80`; `WWW-Authenticate`
  header is parsed by `_classify_challenge()` (`mcp_detect.py:110-125`, RFC 6750: `Bearer`→`bearer`,
  `Basic`→`basic`, anything else→`api_key`), and OAuth metadata discovery is attempted in parallel
  (`_discover_oauth_metadata()`, `mcp_detect.py:224-283` — RFC 9728 `resource_metadata`/`.well-known/oauth-protected-resource`
  → `authorization_servers[]` → RFC 8414/OIDC `.well-known/oauth-authorization-server` or
  `openid-configuration`); if a `token_endpoint` is discovered, a bare `bearer` classification is
  upgraded to `oauth2` (`mcp_detect.py:391-402`).
- No candidate answers → tries OAuth well-known discovery directly against the bare URL as a last
  resort, else reports `reachable=False`, `auth_type="unknown"`, confidence `0.10`.

Every result carries `transport_confidence` (float) and `transport_evidence` (ordered list of
`{source, reason}`), plus `credential_fields` — a list of UI form-field descriptors built by
`_credential_fields(auth_type)` (`mcp_detect.py:128-156`, e.g. `oauth2`→`access_token`+`client_id`+`client_secret`
fields, `api_key`→`api_key` field, `basic`→`username`+`password`).

**Zero provider-specific branching** — confirmed: no vendor/hostname string literal appears anywhere
in `mcp_detect.py`'s classification logic (the module docstring's claim is accurate for this file).

### 2.6 Credential resolution & storage (`mcp_auth.py`)

**[CONFIRMED]** Encryption: `_fernet()` (`mcp_auth.py:66-84`) derives a Fernet key via PBKDF2-HMAC-SHA256
(100,000 iterations, fixed salt `b"mcp_credentials_salt"`) from
`settings.MCP_CREDENTIALS_SECRET or settings.JWT_PRIVATE_KEY` (`src.config.get_settings()`).
`encrypt_credentials()`/`decrypt_credentials()` (`mcp_auth.py:87-99`) wrap this. `store_server_credentials()`
/`load_server_credentials()`/`delete_server_credentials()` (`mcp_auth.py:105-162`) upsert/read/delete
rows in `VendorMCPCredential`, with per-tenant rows overriding the vendor-level (`tenant_id IS NULL`)
fallback.

Main entry point `resolve_auth(db, server_id, server_url, auth_config, credentials, tenant_id, server_name)`
(`mcp_auth.py:339-434`) merges stored + request-supplied credentials (request wins), aliases
`GITHUB_TOKEN`↔`GITHUB_PERSONAL_ACCESS_TOKEN`, then branches on `auth_type`:

- `none`/`env`/`device_pairing` or `transport == "stdio"` → no headers; credentials pass through for
  env-var injection.
- `basic` → `_basic_header()` (`mcp_auth.py:168-172`, `Authorization: Basic base64(user:pass)`).
- `api_key` → `_api_key_header()` (`mcp_auth.py:175-188`, `X-API-Key: <key>` by default, or
  `Authorization: Bearer <key>` if `header_name == "authorization"`).
- `bearer` → `_bearer_header()` (`mcp_auth.py:191-194`).
- `oauth2` → `_resolve_oauth2()` (`mcp_auth.py:437-531`), tried in this order: (1) in-memory
  `_token_cache` (module-level dict, keyed `(server_id_or_url, tenant_id)`, refreshed 60 s before
  expiry — **[CONFIRMED] process-local, not persisted, not shared across the auth/backend process
  pair**); (2) `refresh_token` grant (`_refresh_token_grant`, RFC 6749 §6) — rotated tokens are
  re-persisted via `store_server_credentials`; (3) `client_credentials` grant
  (`_client_credentials_grant`, RFC 6749 §4.4, HTTP Basic client auth); (4) RFC 7591 dynamic client
  registration (`_dynamically_register_client`) followed by a `client_credentials` grant, only if the
  discovered OAuth metadata advertises a `registration_endpoint`; (5) passthrough of a pre-supplied
  `access_token`/`token`/`bearer_token`. Failure at every step raises `McpAuthError`.
- unknown → `_raw_header_passthrough()` (legacy behavior — copies any credential keys that look like
  header names).

### 2.7 Orchestration (`mcp_service.py`) — the two-step lifecycle

**[CONFIRMED]** The module docstring states the design intent and the code matches it:

> Step 1 — Register: analyze source, detect transport/runtime/auth, save normalized config. Does
> NOT connect if credentials missing. Returns 201, status=UNCONNECTED.
> Step 2 — Test Connection: user provides credentials via dynamic form, connect, run initialize +
> tools/list, save tools, status=VERIFIED.

**Step 1 — `add_mcp_server(db, data, actor_id)`** (`mcp_service.py:41-137`):
calls `analyze_repo_normalized(data.source_url)` → builds a legacy `auth_config` dict from the
normalized result → constructs a `VendorMCPServer` row with `status="UNCONNECTED"` and **no**
connection attempt → `db.add()` + `db.flush()` → `log_audit_event(action="mcp_server.add")`. Caller
(`router.post_add_mcp_server`, `router.py:80-94`) does `db.commit()` + `db.refresh()`.

**Step 2 — `test_mcp_connection(db, server, request_credentials, tenant_id)`** (`mcp_service.py:224-341`):
1. Self-heals `transport` to `"stdio"` if `source_type == "github"` and a `command` is present but the
   stored transport is HTTP-ish (`mcp_service.py:237-240`).
2. Resolves auth via `mcp_auth.resolve_auth()` (§2.6).
3. Self-heals Go command args: forces `["run", "."]` if a stale `github.com` module path was stored,
   and appends `"stdio"` if missing (`mcp_service.py:264-268`); strips a stray `"stdio"` positional arg
   for non-Go runtimes (`mcp_service.py:270-272`).
4. Self-heals "filesystem" servers missing a directory argument by appending `/tmp`
   (`mcp_service.py:274-284`).
5. Builds a normalized `config` dict and calls `MCPClient().connect(config)` (§2.3).
6. Persists `server.bound_tools = result["bound_tools"]` (names only), `server.status = "VERIFIED"`,
   `server.auth_type = result.get("auth_type", ...)`, `db.flush()`.
6b. **[CONFIRMED — fixed this pass, was a real gap]** Also deletes and re-inserts one `MCPTool` row
   per `result["tools"]` entry (name, description, `input_schema`), then embeds each (§2.10). Before
   this pass, `test_mcp_connection()` **never created a single `MCPTool` row** — `bound_tools` (tool
   *names* only, no parameter schema) was the only thing persisted from a successful connection, even
   though the `MCPTool`/`vendor_mcp_tools` model and table already existed and `MCPClient.connect()`
   already returned full `{name, description, input_schema}` per tool. This was a genuine prerequisite
   for §2.10/§2.11 — there was nothing to rank or hand to an LLM otherwise.
7. If request credentials were supplied, re-persists them (to capture rotated OAuth tokens).
8. Logs `mcp_server.test_connection` audit event; returns a dict matching `ConnectMCPServerResponse`.

Caller (`router.test_mcp_connection_endpoint`, `router.py:148-208`) short-circuits if
`server.status == "VERIFIED"` already (returns stored `bound_tools`, does not re-connect), otherwise
calls the above and commits; catches `McpAuthError` → `400`, any other exception → `502`, with special
casing to rewrite `"Connection closed"`/`"MCPError"` substrings into a friendlier message, including
unpacking Python 3.11+ `BaseExceptionGroup` sub-exceptions (`router.py:190-207`).

**Legacy one-step path — `create_mcp_server()`** (`mcp_service.py:140-221`) still exists: detects via
`mcp_detect.detect_mcp_server()`, connects immediately if credentials were supplied or no auth is
required, and sets status directly to `VERIFIED`/`UNCONNECTED` based on whether tools were discovered.
Exposed at `POST /mcp/legacy` (`router.py:98-115`).

**Delete/disconnect:**
`delete_mcp_server()` (`mcp_service.py:356-381`) cascades: deletes `TenantResourceGrant` rows for
`resource_type="mcp"`, deletes stored credentials, clears the token cache, calls
`_cleanup_server_local_repo_cache()` (`mcp_service.py:467-485` — regex-parses `source_repo_url` and
`shutil.rmtree`s `/tmp/mcp_repos/<owner>_<repo>` if it exists), deletes the row, logs an audit event.
`disconnect_mcp_server()` (`mcp_service.py:488-498`) does the same cleanup but only resets
`status = "UNCONNECTED"` rather than deleting the row.

### 2.8 Stdio process isolation — recent changes (confirmed via git history + current code)

**[CONFIRMED, current code]** `_sanitize_stdio_env()` (`mcp_client.py:882-900`) strips
`VIRTUAL_ENV`, `PYTHONHOME`, `PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONUSERBASE` from the environment
passed to a spawned stdio server, and removes any `PATH` entry containing a `.venv` component. Its
docstring states the reason: "The backend itself runs under `uv run`, so `os.environ` carries
`VIRTUAL_ENV` (uv then warns... for every spawned server) and potentially `PYTHON*` variables whose
paths could shadow the server's own dependencies." This corresponds to commit
`00869b6 fix(vendor-mcp): stop leaking backend venv state into spawned stdio servers`.

**[CONFIRMED, current code]** `_pick_local_entry()` (`mcp_client.py:639-850`), when it finds a
`pyproject.toml` and `uv` is available (`shutil.which("uv")`), prefers
`["uv", "run", "--directory", str(project_dir), <script-name>]` (or `..., "python", <entry_file>]`)
over invoking the repo's Python code with the backend's own interpreter — this isolates the spawned
server's dependency resolution (e.g. its own `mcp`/`FastMCP` version) from the backend process's
installed packages, and `--directory` also fixes the spawned process's CWD to the nested project root
for repos where the MCP server lives in a subdirectory. This corresponds to commits
`a86dd61`, `211725f`, `1348d42`, `a59816d` (git log, "fix(vendor-mcp): ... uv run ... nested subdirs
... console-script entries").

**[CONFIRMED, current code]** `_pick_local_entry()` also has a "monorepo sub-project check"
(`mcp_client.py:665-682`) that, when the cloned root has no manifest but a subdirectory name containing
`"mcp"` does, recurses into that subdirectory first — corresponding to the "scan nested subdirs" fix
commits.

**[CONFIRMED, current code]** `test_mcp_connection()`'s no-auth-prompt path (any server whose detected
`auth_type` is `"none"`) matches the "stop prompting creds for no-auth stdio servers" commit
(`8f5c244`) — confirmed by the `auth_type in ("none", "env", "device_pairing")` early-return branch in
`resolve_auth()` (§2.6) requiring no credentials.

**[INFERRED]** The specific line-level diffs of each individual commit were not read (git history was
consulted only for commit messages/ordering, per the task's file-reading budget); the summary above is
built from the corresponding logic present in the *current* file, cross-referenced against matching
commit messages, not from `git show` diffs of each commit.

### 2.9 Legacy MCP CRUD surface (`apps/auth/src/api/v1/mcp/`)

**[CONFIRMED]** This is a **separate, simpler MCP-server CRUD implementation**, added in commit
`c7d3d10 add official mcp server` (before the Universal MCP Engine existed), still mounted at
`/api/v1/mcp/*` on the auth service via `api_router.include_router(mcp_router)`
(`apps/auth/src/api/v1/router.py:11,19`). It operates on the **same** `VendorMCPServer` /
`TenantResourceGrant` tables (imported directly, `service.py:22`) but with materially different
behavior than `vendor_resources`:

- `McpServerService.create_server()` (`service.py:31-70`) builds a `VendorMCPServer` directly from
  caller-supplied `name`/`transport`/`server_url`/`bound_tools` — no repo analysis, no transport
  detection, no auth-type detection. If `bound_tools` is omitted it calls
  `_discover_tools()` (`service.py:351-372`), which only handles `transport == "sse"` (a bare
  `GET {server_url}/tools` REST call, not an MCP `initialize`/`tools/list` handshake) and returns `[]`
  for stdio or on any failure.
- Grants use `resource_type="mcp_server"` (`service.py:111, 254, 300, 342` etc.) — **a different
  string than `vendor_resources`'s `"mcp"`** (`mcp_service.py:38,367`). A grant created through one
  system is therefore invisible to the other's `TenantResourceGrant` queries (`catalog_engine.py:42`
  filters on `resource_type == "mcp"`).
- `McpCredentialManager` (`credentials.py`) derives the *same* Fernet key
  (`MCP_CREDENTIALS_SECRET or JWT_PRIVATE_KEY`, identical PBKDF2 parameters as `mcp_auth._fernet()`) but
  **`store_server_credentials()`, `get_server_credentials()`, and `delete_server_credentials()` do not
  persist or read anything** — `store_server_credentials()` only writes an audit-log event and leaves
  a code comment ("For now, store in a simple table... we'll use a runtime approach since we can't
  modify the DB schema here"); `get_server_credentials()` unconditionally `return None`;
  `delete_server_credentials()` returns `True` without touching any table. This module never writes to
  `VendorMCPCredential`.
- `list_credential_configs()` (`credentials.py:136-189`) **does** contain vendor-name string matching
  (`"gmail"`/`"google"` in `server_url` → Google OAuth2 config stub; `"github"` in `server_url` → GitHub
  token config stub) — this is the kind of per-vendor branching that the `vendor_resources` engine's
  design doc explicitly rules out (§13/§25/Rule 8, Rule 15 of `universal_mcp_server_add_connection_flow.md`).

**[CONFIRMED — not used by the frontend]** `web/lib/api.ts` has no calls into `/api/v1/mcp/*`
(grep found only `/vendor/resources/mcp*` calls, all pointed at `BACKEND_API_URL`). This legacy router
is live on the running auth service but **[INFERRED]** appears to be dead code from the frontend's
perspective — it is reachable directly (e.g. via `curl`/API docs) but not driven by the shipped UI.

### 2.10 Embeddings and two-stage hybrid search (`catalog_engine.py`, `hybrid_search.py`)

**[CONFIRMED — fixes a documented defect]** A prior pass of this document found
`get_authorized_vendor_catalog_semantic()` referencing `.dim`/`.embedding` attributes that did not
exist on `VendorMCPServer`, meaning any query-bearing call to `GET /catalog` would raise
`AttributeError` (masked in practice only because the embedding call itself usually failed first,
falling back to an unranked list). This pass adds the missing columns and a real ranking pipeline:

- **`VendorMCPServer`/`MCPTool` gained `embedding` (JSON `list[float]`), `embedding_model` (str),
  `dim` (int)** columns (`models.py:215-217`, `:313-315`; migration
  `apps/auth/alembic/versions/741056495a49_*.py`). `dim` lets callers detect a stale vector after an
  embedding-provider/model switch instead of comparing incompatible vectors.
- **`embed_server()`/`embed_tool()`** (`catalog_engine.py:207`, `:227`) compute and store these
  columns via `embed_text()` → `LLMGateway.embed()` (§1.2), from `"{name}. {description}"` (server) or
  `"{name}. {description} {input_schema property names}"` (tool). Called from `mcp_service.add_mcp_server()`
  (server, at registration) and `mcp_service.test_mcp_connection()` (each discovered tool, after
  `tools/list` — see below) — both **best-effort**: a failed embedding call (no provider configured,
  network error) leaves the row's embedding columns unset rather than failing the surrounding
  operation. `POST /mcp/{id}/embed` (`router.py`) re-runs this for a server and all its tools on demand.
- **`vendor_mcp_tools` rows are now actually persisted.** `test_mcp_connection()` previously only
  updated the legacy `bound_tools` JSON list (tool *names* only, no schema) — it now also deletes and
  re-inserts one `MCPTool` row per discovered tool (name, description, `input_schema`) on every test,
  then embeds each. This is a prerequisite for everything below — there was previously no persisted
  per-tool schema to rank or hand to an LLM.
- **`hybrid_search.py` (new file)** — a generic ranking primitive, `rank(items, *, query,
  query_vector, top_k, text_of, embedding_of, dim_of)` (`hybrid_search.py:233`), used identically for
  servers and tools via accessor callbacks (no per-type branching):
  1. **Vector**: cosine similarity against `query_vector`, only for items whose `dim` matches the
     query embedding's length.
  2. **BM25** (`rank_bm25.BM25Okapi`, `_bm25_rank_indices`, `:143`): lexical ranking over the same
     `text_of()` text. A ~50-word English stopword list (`_STOPWORDS`) is filtered out first — a
     query and a document sharing only a stopword (e.g. both containing "in") was found to
     register as a lexical match otherwise. A monkeypatch (`:158-163`) also floors BM25Okapi's
     **exact-zero** idf (a term whose document frequency is precisely half the corpus — common with
     the small candidate pools here, e.g. 4 tools where a term appears in exactly 2) to the same
     small epsilon `rank_bm25` already uses for *negative* idf; left unpatched, that term
     contributes nothing at all.
  3. **Typo correction** (`_correct_typos`, `:111`): each query token not found in the
     candidate set's own vocabulary is fuzzy-matched (`difflib.get_close_matches`, cutoff `0.8`,
     stdlib — no new dependency) against that vocabulary before the BM25 lookup. Generic by
     construction — it corrects against whatever text the *current* candidates contain, not a fixed
     dictionary.
  4. **Fusion**: (1) and (2) are combined by **Reciprocal Rank Fusion** (`_rrf_fuse`, `:179`, `k=60`,
     the standard RRF paper constant) — fusing by *rank position* rather than raw score sidesteps
     normalizing cosine similarity (0..1) against BM25 (unbounded) onto a common scale.
  5. **Rerank**: the fused top `max(top_k, 20)` shortlist is reranked by a cross-encoder
     (`fastembed.rerank.cross_encoder.TextCrossEncoder`, model `Xenova/ms-marco-MiniLM-L-6-v2`, ~80MB
     ONNX, CPU-only — no torch/CUDA dependency chain; baked into the backend Docker image at build
     time, `docker/Dockerfile.backend`, so first use pays no download). The reranker's own ranking
     is fused back in via a **second, weighted** RRF pass (`weights=[1.0, 0.3]`, `hybrid_search.py:68`,
     `:251`) rather than replacing the fused order outright.
  6. Every stage degrades gracefully to the next-available signal (missing embeddings, no lexical
     overlap, reranker unavailable) rather than raising; the absolute worst case is `items[:top_k]`
     in original order.
- **[CONFIRMED — real regressions found and fixed during manual verification, not just designed
  around]** Against live embeddings: (a) letting the reranker's raw score *replace* the fused order
  (rather than vote-fuse into it) flipped a correct "create_issue" match to "list_pull_requests" for
  a bug-report query; (b) even after vote-fusing at equal weight, the reranker still won on a
  "create a Notion page" query, ranking a "move page" tool above the actual "create page" tool with
  non-trivial confidence — both because a small MS-MARCO-trained passage cross-encoder generalizes
  poorly to terse, imperative-mood tool/API metadata text, not because of a training-data mismatch
  fixable by phrasing tricks (a fully-rewritten natural-sentence version of the same text did score
  correctly, but a purely mechanical `"This tool: {description}"` template did not — the effect was
  not reproducible via any generic, non-hand-authored transformation). The reranker's fusion weight
  was lowered until the arithmetic (worked through by hand against the captured rank lists) recovered
  the correct order, landing on `0.3`.
- **`get_authorized_vendor_catalog_semantic()`** (`catalog_engine.py:93`) — now genuinely functional:
  ranks `get_authorized_vendor_catalog()`'s access-filtered candidates via `hybrid_search.rank()`.
- **`get_relevant_tools_semantic()`** (`catalog_engine.py:121`, new) — the two-stage retrieval this
  whole pipeline exists for: rank access-filtered servers down to `top_k_servers` (stage 1, reusing
  the above), then rank only *those servers'* `MCPTool` rows down to `top_k_tools` (stage 2) — the
  query is embedded once and reused for both stages. Returns `(server, tool, score)` triples; `score`
  is the tool's cosine similarity when an embedding was available, else `None` (BM25/rerank still
  ranked it). Exposed as `GET /catalog/tools` (`router.py:517-556`) — selection only, no tool is
  called (§3.6 unchanged).

### 2.11 Tool-call argument filling (`tool_call_planner.py`)

**[CONFIRMED]** One layer beyond §2.10's selection: `plan_tool_call()` (`tool_call_planner.py:100`)
takes the top few candidates from `get_relevant_tools_semantic()` and asks a **chat** LLM (as
opposed to the embedding call in §2.10) to pick exactly one and fill its `input_schema` via native
OpenAI-style function-calling (`ToolDefinition`/`tool_choice="auto"`, `apps/llm_gateway/types.py` —
already-existing gateway machinery, not new for this feature). Candidate tool names are
disambiguated (`_unique_function_name`, `:57`) when two servers happen to expose a same-named tool.
Exposed as `GET /catalog/plan-tool-call` (`router.py:558-598`).

**[CONFIRMED — explicit non-execution boundary, still holds]** `plan_tool_call()` returns
`(tool_id, tool_name, server_id, server_name, arguments, input_schema, model)` as data. **It does not
call `MCPClient` or any connection code — there is still no `tools/call` invocation anywhere in the
repository** (§3.6, unchanged by this entire pass). The arguments the LLM fills are not validated
against `input_schema` before being returned — confirmed live: for a QuickBooks report tool whose
schema requires a `params` wrapper object with no required sub-fields, and a query specifying no
filters, the model returned bare `{}` rather than the schema-satisfying `{"params": {}}`. The system
prompt (`tool_call_planner.py:37`) was tuned once during manual verification: the original wording
("if none of the tools can genuinely satisfy the request, do not call any tool") caused the model to
decline entirely whenever a required parameter wasn't explicit in the query, even with an obviously
correct candidate tool present (confirmed live for "send message to whatsapp" and "create page on
notion" against real candidate schemas) — it now explicitly frames the response as a
human-reviewed proposal and asks for a best-guess/placeholder value instead of declining, verified to
still correctly decline when candidates are genuinely unrelated to the query.

### 2.12 OAuth "Connect via provider" bootstrap (`oauth_flow.py`)

**[CONFIRMED]** `mcp_auth._resolve_oauth2()` (§2.6) already implemented `client_credentials`,
`refresh_token`, and RFC 7591 dynamic-registration grants, but had no `authorization_code` grant —
the interactive human-consent step some providers require to obtain the *first* refresh token
(client_credentials alone doesn't work for every provider). `oauth_flow.py` adds only that bootstrap
step; every subsequent call still goes through the existing `_resolve_oauth2()` refresh-token path.

- **One fixed callback URL for every server, not one per server** (`callback_redirect_uri()`,
  `oauth_flow.py:83`; endpoint `GET /mcp/oauth/callback`, `router.py:448-494`, intentionally
  unauthenticated — the provider itself is the caller). Providers require an exact, pre-registered
  redirect URI, and MCP servers are created with random UUIDs, so a per-server URI isn't practical;
  the opaque `state` parameter (round-tripped unmodified by every OAuth provider per spec) carries
  which server/tenant a given flow belongs to, held in an in-memory `_pending` dict
  (`_PendingAuthorization`, `:51`, 10-minute TTL) keyed by `state` — same "short-lived in-process
  cache" convention already used elsewhere in this codebase (`mcp_auth._token_cache`,
  `catalog_engine`'s analysis cache in §2.4).
- **`PATCH /mcp/{id}/oauth-config`** — admin manually supplies `authorization_endpoint`/
  `token_endpoint`/`scope` for servers whose OAuth metadata can't be auto-discovered (a local stdio
  server isn't running yet at analysis time, so RFC 8414 discovery has nothing to probe — confirmed
  needed live for a QuickBooks-Online-style stdio server; most providers publish these as fixed,
  documented URLs).
- **`POST /mcp/{id}/oauth/authorize`** (`build_authorize_url()`, `:88`) — builds the provider's
  consent URL from the server's `auth_config["oauth"]` + admin-supplied `client_id`/`client_secret`.
- **`GET /mcp/oauth/callback`** (`complete_authorization()`, `:157`) exchanges the code
  (`mcp_auth.exchange_authorization_code()`, new grant function in `mcp_auth.py`, alongside the
  existing `_refresh_token_grant`/`_client_credentials_grant`) and persists the result via the
  existing `store_server_credentials()`. **Provider-specific extra callback params are handled
  generically, not per-vendor**: any query param beyond `code`/`state` (e.g. Intuit's own `realmId`,
  not part of the OAuth2 spec) is stored under its own name *and* fuzzy-matched
  (`_match_declared_field()`, `:144` — folds case/underscores, e.g. `realmId` → `REALM_ID`) against
  the server's own detected credential field names, so it lines up with whatever env-var name §2.4's
  detection actually found for that server.
- The callback page (`_oauth_result_html()`, `router.py`) posts a `window.postMessage` back to
  `window.opener` (the admin dashboard tab that opened it as a popup) and auto-closes on success —
  every interpolated value is escaped (`html.escape`)/JSON-encoded, since `error_description` on the
  failure path can originate from the OAuth provider's own redirect, not just this codebase.
- **[CONFIRMED — genuine bug found and fixed during manual verification]** The admin dashboard
  modal that surfaces this flow (`web/app/vendor/tools/page.tsx`) initially failed to show the
  "Connect via OAuth" button immediately after saving OAuth endpoints — the modal's `server` prop was
  a snapshot taken when it opened, and saving endpoints invalidated the servers list query without
  the modal picking up the refetched row. Fixed by having the parent look the server up fresh from
  the list on every render (`servers.find((s) => s.id === connectServer.id)`) instead of holding onto
  the stale object.

---

## 3. Execution flow

### 3.1 Process entry points

**[CONFIRMED]** Two independent ASGI apps, each importable as a module-level `app`:

- `apps.auth.src.main:app` — `uvicorn src.main:app --port 8001` (or `--app-dir apps/auth`).
- `apps.backend.main:app` — `uvicorn apps.backend.main:app --port 8002`.

Both prepend the repo root and `apps/auth`, `apps/backend` to `sys.path` at import time
(`src/main.py:20-23`, `apps/backend/main.py:20-23`) so that `src.*` and `vendor_resources.*` absolute
imports resolve regardless of the process's working directory.

### 3.2 Initialization sequence (either process)

1. `sys.path` mutation (module top-level, before any `src.*`/`vendor_resources.*` import).
2. Import-time singletons constructed: `get_auth_settings()`/`get_settings()`
   (`Settings`, pydantic-settings, cached via `@lru_cache` — **[CONFIRMED]** `get_backend_settings()`
   at `apps/backend/config.py:37` uses `@lru_cache`; `get_settings()` in `apps/auth/src/config.py` was
   not re-quoted here but is referenced the same way throughout).
3. `create_app()` builds the `FastAPI` instance, registers CORS middleware, health route, and
   (auth only) the JWKS route, then includes routers.
4. **Lifespan startup** (`asynccontextmanager`, both processes):
   `await asyncio.to_thread(run_migrations)` — runs Alembic (`apps/auth/src/db/migrations.py:21`) to
   `head` in a worker thread (Alembic's own `env.py` calls `asyncio.run()`, which cannot nest inside
   the already-running event loop). On any exception, falls back to
   `await create_db_tables()` (`src/db/session.py:35`, a `Base.metadata.create_all` style call).
   Auth's lifespan additionally prints `settings.redacted_repr()` if `SHOW_LOADED_ENV` is set.
5. Each process now serves requests. **[CONFIRMED]** No explicit shutdown hook logic exists beyond
   what the bare `yield` in each `lifespan` implies (no `finally:` block, no explicit
   engine-disposal call) — **[INFERRED]** cleanup is left to normal Python/async-context-manager
   garbage collection and `uvicorn`'s own shutdown sequence; **[UNKNOWN]** whether the underlying
   `AsyncEngine` connection pool is explicitly disposed on SIGTERM (not traced further, no shutdown
   code path was found to trace).

### 3.3 Component creation / dependency flow (a single MCP request)

**[CONFIRMED]** No dependency-injection container beyond FastAPI's own `Depends()`. A typical
authenticated request (e.g. `POST /api/v1/vendor/resources/mcp/{server_id}/test`) resolves
dependencies in this order:

```text
┌──────────────────────────────────────────────┐
│ Incoming authenticated MCP API request      │
│ POST /mcp/{server_id}/test                   │
└──────────────────────┬───────────────────────┘
                       ▼
              ┌───────────────────┐
              │ FastAPI Depends() │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │ get_current_user  │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │ Decode JWT        │
              │ RS256 validation  │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │ SELECT User /     │
              │ VendorUser by ID  │
              └─────────┬─────────┘
                        ▼
                ┌───────────────┐
                │ Tenant user?  │
                └──────┬───┬────┘
                     Yes   No
                      │     │
                      ▼     │
              ┌───────────────┐
              │ Set tenant/RLS │
              │ context        │
              └──────┬────────┘
                     │
                     └──────┬──────┘
                            ▼
                  ┌─────────────────┐
                  │ Build CurrentUser│
                  └────────┬────────┘
                           ▼
                  ┌─────────────────┐
                  │ Role allowed?   │
                  └──────┬────┬─────┘
                       No│    │Yes
                         ▼    ▼
                    ┌──────┐ ┌────────────────┐
                    │ 403  │ │ Route handler  │
                    │Denied│ │ executes       │
                    └──────┘ └────────────────┘
```

No object is constructed and reused across requests except: the module-level `_token_cache` dict in
`mcp_auth.py` (process-local OAuth token cache) and the `@lru_cache`d settings singletons. `MCPClient`
is instantiated fresh per call (`mcp_service.py:310` — `client = MCPClient()`), not cached.

### 3.4 MCP connection establishment (Step 1 → Step 2, end to end)

```text
MCP CONNECTION LIFECYCLE

┌───────────────┐
│ Client / UI   │
└───────┬───────┘
        │
        ▼
┌─────────────────────────────┐
│ STEP 1: Register MCP server │
│ POST /mcp                   │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ Analyze source              │
│ • GitHub                    │
│ • Remote HTTP               │
│ • Local filesystem          │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ Save server registry        │
│ status = UNCONNECTED        │
└──────────────┬──────────────┘
               │
               ▼
        STEP 2: Connect
               │
               ▼
┌─────────────────────────────┐
│ Resolve authentication      │
└──────────────┬──────────────┘
               │
       ┌───────┼────────┬─────────┬─────────┐
       ▼       ▼        ▼         ▼         ▼
    Basic   API Key   Bearer    OAuth2    None/env
                                  │
                                  ▼
                    ┌────────────────────────┐
                    │ OAuth2 resolution      │
                    │ 1. Cache               │
                    │ 2. Refresh token       │
                    │ 3. Client credentials  │
                    │ 4. Dynamic registration│
                    │ 5. Passthrough token   │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │ Build connection config │
                    └───────────┬────────────┘
                                ▼
                    ┌────────────────────────┐
                    │ MCPClient.connect()    │
                    └───────────┬────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
        ┌──────────┐      ┌────────────┐      ┌──────────┐
        │  STDIO   │      │ Streamable │      │   SSE    │
        │          │      │    HTTP    │      │          │
        └────┬─────┘      └─────┬──────┘      └────┬─────┘
             │                  │                  │
             ▼                  ▼                  ▼
       Spawn process       HTTP POST          HTTP GET /
                                             event-stream
             │                  │                  │
             └──────────────────┼──────────────────┘
                                ▼
                    ┌────────────────────────┐
                    │ ClientSession          │
                    │ initialize()           │
                    │ list_tools()           │
                    └───────────┬────────────┘
                                ▼
                    ┌────────────────────────┐
                    │ Save discovered tools  │
                    │ status = VERIFIED      │
                    └────────────────────────┘
```

### 3.5 Tool/resource discovery

**[CONFIRMED]** Discovery happens exactly once per Step-2 call, via `ClientSession.list_tools()`
(§2.3/§3.4) — this is the **only** tool-discovery mechanism in the codebase; there is no periodic
refresh, no webhook, no polling loop. Re-discovery requires calling `POST /mcp/{id}/test` again, which
the router short-circuits away from if `status == "VERIFIED"` (`router.py:165-173`) — so, as currently
wired, a verified server's tool list is **never automatically refreshed**; the only ways to force
re-discovery are (a) `disconnect_mcp_server()` first (resets to `UNCONNECTED`), or (b) the legacy
`POST /mcp/{id}/connect` endpoint (`router.py:235-285`), which calls `connect_registered_server()` →
`test_mcp_connection()` unconditionally (no `VERIFIED` short-circuit in that code path).

### 3.6 Request execution against a discovered tool

**[CONFIRMED — does not exist]** There is no endpoint or service function in the current codebase
that invokes a specific discovered MCP *tool* (i.e., no `tools/call` JSON-RPC invocation appears
anywhere in `apps/backend`). The only MCP protocol calls made are `initialize` and `tools/list`
(§2.3/§3.4). The old `ARCHITECTURE.md`'s `execute_spec()`/`invoke_tool()` DAG-execution pipeline
(LangGraph `StateGraph`, `AgentState`, per-node tool invocation) is **absent from the current source
tree** — no `executor.py`, `tool_executor.py`, or `compiler.py` file exists under
`apps/backend/vendor_resources` or anywhere else in the repo (confirmed by directory listing, §0).
Correspondingly, the `CompiledAgentSpec`/`AgentNode`/`AgentEdge`/`CompileAgentRequest`/`RunAgentRequest`
/`RunAgentResponse` Pydantic schemas still exist in `schemas.py:300-351`, but **grep across
`apps/backend` found no router or service that imports or returns any of them** — they are
unreferenced schema definitions with no wired endpoint.

### 3.7 Error handling

**[CONFIRMED]** Two custom exception types: `McpDetectError` (`mcp_detect.py:96-97`, raised only for
empty `server_url` input) and `McpAuthError` (`mcp_auth.py:59-60`, raised throughout `mcp_auth.py` on
credential/token failures). Router-level handling (`router.py:174-207`, duplicated near-identically at
`router.py:251-284` for the legacy connect endpoint):

- `McpAuthError` → `HTTPException(400, "Credential resolution failed: {exc}")`, `db.rollback()`.
- Any other `Exception` → logged via `logger.exception(...)`, `db.rollback()`, message post-processed
  (unpacks `BaseExceptionGroup` sub-exceptions, rewrites `"Connection closed"`/`"MCPError"` substrings
  to a friendlier string) → `HTTPException(502, "Connection failed: {err_msg}")`.
- `detect_mcp_server_endpoint` catches only `McpDetectError` → `400`.
- `analyze_mcp_repo_endpoint` catches any `Exception` → `400`.

**[CONFIRMED]** Within `mcp_client.py`, network/handshake failures are not swallowed silently at the
transport level — `_handshake()` and `_connect_stdio()` let exceptions propagate up to the router's
generic `except Exception` handler above (no per-adapter try/except). The **legacy** free function
`connect_mcp_server()` (`mcp_client.py:392-444`) does catch per-attempt exceptions when trying
`streamable_http` then falling back to `sse`, re-raising a `ConnectionError` only if both fail.

### 3.8 Shutdown / cleanup

**[CONFIRMED]** Repo-cleanup on delete/disconnect is explicit and synchronous:
`_cleanup_server_local_repo_cache()` (§2.7) removes `/tmp/mcp_repos/<owner>_<repo>` via
`shutil.rmtree(..., ignore_errors=True)`. Credential cleanup: `delete_server_credentials()` (removes
all `VendorMCPCredential` rows for the server) and `clear_token_cache()` (drops in-memory OAuth cache
entries for that server). **[CONFIRMED]** No cleanup exists for `/tmp/repo_analysis/<owner>_<repo>`
(the directory used during Step-1 analysis) beyond the `finally: shutil.rmtree(clone_dir)` inside
`_analyze_github_repo_normalized()` itself (§2.4) — i.e. that clone is removed synchronously at the
end of the same function call, not left for later cleanup. **[CONFIRMED]** No process-level shutdown
hook exists for spawned stdio child processes beyond the `async with stdio_client(params) as (...)`
context manager in `_connect_stdio()` (`mcp_client.py:1028-1029`) — the child process lifecycle is
scoped to that `async with` block, meaning **the tool-discovery connection is closed immediately after
`_session_details()` returns**; there is no persistent/pooled stdio process kept alive across requests
for repeated tool invocation (which is moot per §3.6 — there is no tool-invocation endpoint to keep it
alive for).

### 3.9 Auth login / signup request flow (non-MCP, auth service)

**[CONFIRMED]** This is the other major request pattern in the repo, independent of the MCP flows in
§3.4-§3.6:

```text
AUTHENTICATION FLOW

┌────────────────────────────┐
│ Frontend Client            │
│ POST /auth/login           │
│ email + password           │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ Auth Router                │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ Auth Service               │
│ Find user by email         │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ Database                   │
│ User / VendorUser          │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ Verify password            │
│ Argon2id                   │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ create_token_pair()        │
└─────────────┬──────────────┘
              │
        ┌─────┴─────┐
        ▼           ▼
┌────────────┐ ┌─────────────┐
│ Access JWT │ │ Refresh JWT │
│ RS256      │ │ RS256       │
└─────┬──────┘ └──────┬──────┘
      │               │
      └───────┬───────┘
              ▼
┌────────────────────────────┐
│ Store refresh-token hash   │
│ + audit login event        │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ 200 OK                     │
│ access + refresh token     │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ Later API request          │
│ Authorization: Bearer JWT  │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ decode_token()             │
│ Validate RS256 / issuer /  │
│ audience / expiry          │
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│ Load user from DB          │
└─────────────┬──────────────┘
              ▼
       ┌───────────────┐
       │ Tenant user?  │
       └──────┬───┬────┘
            Yes   No
             │     │
             ▼     │
       ┌──────────┐ │
       │ Set RLS  │ │
       └────┬─────┘ │
            └───┬───┘
                ▼
       ┌────────────────┐
       │ CurrentUser    │
       └───────┬────────┘
               ▼
       ┌────────────────┐
       │ Role allowed?  │
       └──────┬────┬────┘
            No│    │Yes
              ▼    ▼
           ┌────┐ ┌──────────────┐
           │403 │ │ Route runs   │
           └────┘ └──────────────┘
```

`POST /auth/refresh` repeats the `create_token_pair`/`RefreshToken` steps after validating the
presented refresh token against its stored hash and `revoked`/`expires_at` fields (exact validation
branch names were not individually re-quoted in this pass — **[INFERRED]** from `service.py`'s
overall structure, not verbatim-quoted here). `POST /auth/logout` marks the presented refresh token
`revoked=True`.

### 3.10 Frontend request lifecycle (`web/lib/api.ts`)

**[CONFIRMED]** Every UI-triggered request funnels through one `request<T>()` helper:

```text
FRONTEND REQUEST<T>() FLOW

┌─────────────────────────────┐
│ UI component calls API      │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ request<T>()                │
│ web/lib/api.ts              │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ Add Authorization: Bearer   │
│ access token                │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ fetch(base + path)          │
└──────────────┬──────────────┘
               ▼
        ┌─────────────────┐
        │ HTTP status?    │
        └──────┬──────────┘
       ┌───────┼──────────────┐
       ▼       ▼              ▼
   2xx OK    401 + token    Other error
       │       │              │
       ▼       ▼              ▼
 Return T  Refresh token    Throw ApiError
               │
               ▼
     ┌──────────────────────┐
     │ Read refreshToken    │
     │ from auth store      │
     └──────────┬───────────┘
                ▼
     ┌──────────────────────┐
     │ POST /auth/refresh   │
     └──────────┬───────────┘
                ▼
       ┌─────────────────┐
       │ Refresh success?│
       └──────┬─────┬────┘
            Yes     No
             │       │
             ▼       ▼
    ┌─────────────┐ ┌──────────┐
    │ Save new JWT│ │ Logout   │
    └──────┬──────┘ └────┬─────┘
           │              │
           ▼              ▼
┌──────────────────┐   Throw error
│ Retry original   │
│ request ONCE     │
└────────┬─────────┘
         ▼
  ┌──────────────┐
  │ Retry 2xx?   │
  └──────┬───┬───┘
       Yes│   │No
          ▼   ▼
      Return T  Throw error
```

No request-level retry/backoff beyond this single 401-triggered refresh-and-retry; no client-side
caching beyond React Query's own defaults (`retry: 1`, `refetchOnWindowFocus: false`, §1.4).

---

## 4. Class / function call graph — key components

> Format: File · Name · Responsibility · Caller(s) · Callee(s) · Inputs · Outputs.

### `VendorMCPServer` (class)
- **File**: `apps/backend/vendor_resources/models.py:53`
- **Responsibility**: ORM row for one MCP server registry entry (any transport/source).
- **Caller**: constructed by `mcp_service.add_mcp_server()`, `mcp_service.create_mcp_server()`,
  `apps/auth/src/api/v1/mcp/service.py:McpServerService.create_server()`; queried by
  `mcp_service.get_mcp_server()`, `mcp_service.list_mcp_servers()`, `catalog_engine.get_authorized_vendor_catalog()`.
- **Callees**: none (data class); inherits `Base`, `TimestampMixin` (`src/db/base.py`).
- **Relationship**: FK target of `VendorMCPCredential.server_id` and `MCPTool.mcp_server_id`; referenced by
  `TenantResourceGrant.resource_id` (loosely — no FK constraint, string equality only).

### `analyze_repo_normalized(repo_url: str) -> NormalizedMCPConfig`
- **File**: `apps/backend/vendor_resources/services/repo_analyzer.py:531`
- **Responsibility**: entry point for source analysis; dispatches to github/remote/local sub-analyzers.
- **Caller**: `mcp_service.add_mcp_server()` (`mcp_service.py:61`).
- **Callees**: `detect_source_type()`, `_analyze_github_repo_normalized()`,
  `_analyze_remote_http_normalized()` (→ `mcp_detect.detect_mcp_server()`), `_analyze_local_path_normalized()`.
- **Inputs**: a source URL or local path string.
- **Outputs**: `NormalizedMCPConfig` dataclass (transport/runtime/auth/command/evidence).

### `detect_mcp_server(server_url, credentials=None, timeout=10.0) -> dict`
- **File**: `apps/backend/vendor_resources/services/mcp_detect.py:291`
- **Responsibility**: live, standards-driven probing of an MCP endpoint to classify transport + auth.
- **Caller**: `router.detect_mcp_server_endpoint()` (`router.py:226`, direct pre-add probe),
  `repo_analyzer._analyze_remote_http_normalized()` (`repo_analyzer.py:662`),
  `mcp_service.create_mcp_server()` (legacy path, `mcp_service.py:149`).
- **Callees**: `_candidate_urls()`, `_probe_endpoint()`, `_classify_challenge()`,
  `_discover_oauth_metadata()` (→ `_authorization_server_metadata()`, `_fetch_json()`), `_result()`.
- **Inputs**: `server_url` (str), optional `credentials` (unused in current logic — accepted but not
  read anywhere in the function body; **[CONFIRMED]** the parameter exists in the signature but
  no branch inside the function reads `credentials`).
- **Outputs**: dict with `ok, transport, endpoint, reachable, auth_required, auth_type, confidence,
  credential_fields, hints, oauth, transport_confidence, transport_evidence, error`.

### `MCPClient.connect(config: dict) -> dict`
- **File**: `apps/backend/vendor_resources/services/mcp_client.py:98`
- **Responsibility**: dispatch to the transport-specific adapter and return normalized discovery result.
- **Caller**: `mcp_service.test_mcp_connection()` (`mcp_service.py:311`).
- **Callees**: `_stdio_adapter()`, `_streamable_http_adapter()`, `_sse_adapter()` (each → `_handshake()`
  or `_connect_stdio()` → `_session_details()`).
- **Inputs**: normalized `config` dict (`transport_type`, `credentials`, `auth_headers`, plus
  transport-specific keys: `command`/`args`/`working_directory`/`env_vars`/`source_repo_url` for
  stdio, `endpoint` for HTTP/SSE).
- **Outputs**: `{transport, bound_tools: [names], tools: [{name, description, input_schema}],
  server_info, protocol_version, auth_type}`.

### `resolve_auth(db, server_id, server_url, auth_config, credentials, tenant_id, server_name) -> dict`
- **File**: `apps/backend/vendor_resources/services/mcp_auth.py:339`
- **Responsibility**: turn a server's detected auth requirement + stored/request credentials into
  ready-to-use HTTP headers (or a credential dict for stdio env injection).
- **Caller**: `mcp_service.test_mcp_connection()` (`mcp_service.py:248`),
  `mcp_service.create_mcp_server()` (legacy, `mcp_service.py:164`).
- **Callees**: `load_server_credentials()`, `_basic_header()`, `_api_key_header()`, `_bearer_header()`,
  `_resolve_oauth2()` (→ `_cache_get()`, `_refresh_token_grant()`, `_client_credentials_grant()`,
  `_dynamically_register_client()`, `_cache_put()`, `store_server_credentials()`).
- **Inputs**: as named; `auth_config` is the server's stored `{auth_type, transport, oauth, ...}` blob.
- **Outputs**: `{headers: dict, credentials: dict, auth_type: str, token_source: str|None}`.

### `add_mcp_server(db, data: AddMCPServerRequest, actor_id) -> VendorMCPServer`
- **File**: `apps/backend/vendor_resources/services/mcp_service.py:41`
- **Responsibility**: Step 1 of the two-step lifecycle — analyze + register, no connection.
- **Caller**: `router.post_add_mcp_server()` (`router.py:80`).
- **Callees**: `analyze_repo_normalized()`, `VendorMCPServer(...)` constructor, `db.add`/`db.flush`,
  `log_audit_event()`.
- **Inputs**: `AddMCPServerRequest` (name, description, source_url, optional source_type/subpath/branch).
- **Outputs**: the persisted (flushed, not yet committed) `VendorMCPServer` row.

### `test_mcp_connection(db, server, request_credentials, tenant_id) -> dict`
- **File**: `apps/backend/vendor_resources/services/mcp_service.py:224`
- **Responsibility**: Step 2 — resolve auth, self-heal known-bad configs, connect, persist discovered
  tools, flip status to `VERIFIED`.
- **Caller**: `router.test_mcp_connection_endpoint()` (`router.py:176`),
  `connect_registered_server()` (`mcp_service.py:459`, itself called by the legacy
  `router.connect_mcp_server_endpoint()`).
- **Callees**: `mcp_auth.resolve_auth()`, `MCPClient().connect()`, `mcp_auth.store_server_credentials()`,
  `log_audit_event()`.
- **Inputs**: a `VendorMCPServer` ORM instance (not just an id — caller must have already fetched it),
  optional request credentials, optional `tenant_id`.
- **Outputs**: `{transport, bound_tools, tools, server_info, protocol_version, auth_type, status}`.

### `get_authorized_vendor_catalog(db, user: CurrentUser) -> list[VendorMCPServer]`
- **File**: `apps/backend/vendor_resources/services/catalog_engine.py:24`
- **Responsibility**: role-based access filter — the single source of truth for "which MCP servers can
  this caller see."
- **Caller**: `router.get_catalog()` (`router.py:309`), `get_authorized_vendor_catalog_semantic()`
  (`catalog_engine.py:73`, as its unranked candidate pool).
- **Callees**: none beyond SQLAlchemy `select()`.
- **Inputs**: `CurrentUser` (role, tenant_id).
- **Outputs**: list of `VendorMCPServer` — `VENDOR_ADMIN` sees all; `SOLO_USER` sees `is_global=True`
  only; tenant roles see `is_global=True` **OR** `id IN (SELECT resource_id FROM tenant_resource_grants
  WHERE tenant_id=... AND resource_type='mcp')`.

### `get_authorized_vendor_catalog_semantic(db, user, query, top_k=5, embedding_provider=None)`
- **File**: `apps/backend/vendor_resources/services/catalog_engine.py:93`
- **Responsibility**: rank the access-filtered catalog against `query` via hybrid search (§2.10).
- **Caller**: `router.get_catalog()` when `q` query param is present.
- **Callees**: `get_authorized_vendor_catalog()`, `embed_text()`, `hybrid_search.rank()`.
- **[CONFIRMED — previously-documented defect fixed this pass]**: `VendorMCPServer` now has real
  `embedding`/`dim`/`embedding_model` columns (§2.10), so the `AttributeError` a prior pass of this
  document found here (`.dim`/`.embedding` referenced but absent) no longer occurs — verified live
  against real embeddings, not just by code reading.

### `get_relevant_tools_semantic(db, user, query, top_k_servers=5, top_k_tools=8, embedding_provider=None)`
- **File**: `apps/backend/vendor_resources/services/catalog_engine.py:121`
- **Responsibility**: the two-stage server→tool retrieval behind `GET /catalog/tools` (§2.10).
- **Caller**: `router.search_catalog_tools()` (`GET /catalog/tools`), `plan_tool_call()` (below).
- **Callees**: `get_authorized_vendor_catalog()`, `embed_text()`, `hybrid_search.rank()` (×2, servers
  then tools).
- **Outputs**: `list[(VendorMCPServer, MCPTool, score: float | None)]`, best match first.

### `hybrid_search.rank(items, *, query, query_vector, top_k, text_of, embedding_of, dim_of)`
- **File**: `apps/backend/vendor_resources/services/hybrid_search.py:233`
- **Responsibility**: generic vector+BM25+rerank ranking primitive — see §2.10 for the full algorithm
  and the two live-verified reranker regressions that shaped its weighting.
- **Caller**: `catalog_engine._rank_servers()`/`_rank_tools()` (thin accessor-binding wrappers).
- **Callees**: `cosine_similarity()`, `_bm25_rank_indices()` (→ `_correct_typos()`, `rank_bm25.BM25Okapi`),
  `_rrf_fuse()`, `_rerank_scores()` (→ `fastembed.rerank.cross_encoder.TextCrossEncoder`, lazily
  loaded once via `@lru_cache`).

### `plan_tool_call(db, *, user, query, top_k_servers=5, top_k_tools=3, provider=None, model=None)`
- **File**: `apps/backend/vendor_resources/services/tool_call_planner.py:100`
- **Responsibility**: select one tool from `get_relevant_tools_semantic()`'s candidates and fill its
  arguments via chat-LLM function-calling (§2.11). Does not call the tool.
- **Caller**: `router.plan_tool_call_endpoint()` (`GET /catalog/plan-tool-call`).
- **Callees**: `get_relevant_tools_semantic()`, `llm_gateway_client.get_gateway()` →
  `LLMGateway.complete()` (this is now the second in-repo caller of `.complete()` — see the entry
  below).
- **Outputs**: `ToolCallPlanResult(plan: ToolCallPlan | None, candidates_considered, message)`; `plan`
  is `None` with a `message` explaining why when no candidate was confident, the LLM was unreachable,
  or there were no candidates at all.

### `oauth_flow.build_authorize_url()` / `complete_authorization()`
- **File**: `apps/backend/vendor_resources/services/oauth_flow.py:88`, `:157`.
- **Responsibility**: the two halves of the OAuth "Connect via provider" bootstrap — see §2.12.
- **Caller**: `router.start_mcp_oauth_authorize()` / `router.mcp_oauth_callback()`.
- **Callees**: `mcp_auth.exchange_authorization_code()` (new grant function alongside the existing
  `_refresh_token_grant`/`_client_credentials_grant` in `mcp_auth.py`), `mcp_service.get_mcp_server()`.

### `Roles`, `CurrentUser`, `get_current_user()`, `require_roles()`
- **Files**: `apps/auth/src/core/roles.py:14`, `apps/auth/src/api/deps.py:22,33,97`.
- **Responsibility**: the single shared identity/authorization primitive, reused unmodified by both
  the auth service's own routers and every `vendor_resources` route (`from src.api.deps import
  CurrentUser, get_current_user, require_roles` — `router.py:25`).
- **Caller**: every protected route in both services.
- **Callees**: `decode_token()` (`src/core/security.py`), `set_tenant_context()` (`src/db/rls.py`),
  SQLAlchemy `select(User)`/`select(VendorUser)`.

### `create_token_pair(sub, tid, wid, role)` / `decode_token(token, expected_type=None)`
- **File**: `apps/auth/src/core/security.py`.
- **Responsibility**: mint/verify the RS256 JWT access+refresh pair that is the sole credential
  format used across both services.
- **Caller**: `create_token_pair` ← `auth/service.login`/`refresh_tokens`/`sso_service.handle_callback`;
  `decode_token` ← `api/deps.get_current_user()`.
- **Callees**: `create_token` (×2 per pair) → `_load_private_key`/`_key_id`; `decode_token` →
  `get_keypair` → `jwt.decode`.
- **Inputs/Outputs**: subject/tenant/workspace/role in → signed JWT string(s) out (`create_token_pair`);
  JWT string in → validated claims dict out (`decode_token`), raising on expiry/signature/issuer/audience mismatch.

### `LLMGateway.complete(request, *, provider=None, fallback=True)` / `.embed(texts, *, model=None, provider=None)`
- **File**: `apps/llm_gateway/gateway.py`.
- **Responsibility**: pick a configured provider client, apply the retryable-only fallback chain
  (`complete`) or the any-error/no-Groq fallback chain (`embed`), return a normalized response.
- **Caller**: **[CONFIRMED — no longer true, was accurate before this pass]** `complete` is now
  called from `apps/backend`: `tool_call_planner.plan_tool_call()` (§2.11), via the shared
  `llm_gateway_client.get_gateway()` singleton (new — avoids constructing a second `LLMGateway`, and
  therefore a second set of provider HTTP clients, alongside `embed_text()`'s). Live-verified against
  real Azure OpenAI (`gpt-4.1-mini`) and Gemini. `embed` ← `catalog_engine.embed_text()`, also now via
  the same shared singleton.
- **Callees**: `_build_try_order()`, `self._clients[name].complete()`/`.embed()` →
  `LiteLLMClient.complete()`/`.embed()` → `litellm.acompletion()`/`litellm.aembedding()` →
  `_map_litellm_error()` on failure.
- **Inputs/Outputs**: `CompletionRequest`/`list[str]` in → `CompletionResponse`/`EmbeddingResponse` out,
  or a subclass of `LLMGatewayError` raised after all providers in the try-order are exhausted.

### `PromptRegistry.format(prompt_type, provider=None, **kwargs)`
- **File**: `apps/llm_gateway/prompts/registry.py`.
- **Responsibility**: render one of the 9 `PromptType` templates with caller-supplied variables.
- **Caller**: **[CONFIRMED] none found in the current repository** — no file under `apps/backend` or
  `apps/auth` calls `PromptRegistry.format`/`get_template` (the only historical caller, the AI
  compiler's `AGENT_COMPILER` prompt construction, no longer exists per §3.6).
- **Callees**: `get_template()` → `_CUSTOM_OVERRIDES` (always empty) / `_TEMPLATES` lookup.
- **Inputs/Outputs**: `PromptType` + kwargs in → formatted prompt string out, or `KeyError` on a missing template variable.

---

## 5. Architecture diagrams

### 5.1 Overall current architecture

```text
OVERALL ARCHITECTURE

                         ┌──────────────────┐
                         │   EnterpriseAI   │
                         │    Monorepo      │
                         └────────┬─────────┘
                                  │
          ┌───────────────────────┼────────────────────────┐
          │                       │                        │
          ▼                       ▼                        ▼
┌──────────────────┐   ┌─────────────────────┐   ┌──────────────────┐
│ apps/auth        │   │ apps/backend        │   │ apps/llm_gateway │
│ Port 8001        │   │ Port 8002           │   │ Port 4000        │
│                  │   │                     │   │                  │
│ Auth / SSO       │   │ MCP resource router │   │ LLMGateway       │
│ Tenant / Vendor  │   │ MCP services        │   │ complete()       │
│ Dashboard / MCP  │   │ Catalog             │   │ embed()          │
└────────┬─────────┘   └──────────┬──────────┘   └────────┬─────────┘
         │                        │                       │
         │                        │                       │
         └──────────────┬─────────┘                       │
                        ▼                                 │
              ┌─────────────────────┐                     │
              │ Shared SQLite DB    │                     │
              │ data/auth.db        │                     │
              │                     │                     │
              │ Two AsyncEngines    │                     │
              └─────────────────────┘                     │
                                                        │
                                                        ▼
                                             ┌──────────────────┐
                                             │ OpenAI / Groq /  │
                                             │ Gemini via       │
                                             │ LiteLLM          │
                                             └──────────────────┘

Backend MCP engine
        │
        ├── repo_analyzer ───────► GitHub / raw repositories
        │
        ├── mcp_detect ──────────► Remote MCP servers
        │
        ├── mcp_client ──────────► HTTP / SSE / stdio
        │                              │
        │                              └──► Local child processes
        │
        └── mcp_auth ────────────► OAuth token endpoints

NOTE:
The llm-gateway HTTP container exists, but current in-repo
catalog code imports LLMGateway directly in-process.
```

> **Docker-only (unused by app code):** `redis` (no Python redis client import found) and the `llm-gateway` container's HTTP surface (nothing in the repo calls port 4000 over the network — only the in-process class import shown above is used).

### 5.2 MCP architecture (client/registry only — no MCP server is hosted by this repo)

```text
MCP ROUTER / SERVICE ARCHITECTURE

┌─────────────────────────────────────────────┐
│ vendor_resources.router                    │
│ /api/v1/vendor/resources                   │
└──────────────────┬──────────────────────────┘
                   │
       ┌───────────┼──────────────┬──────────────┐
       ▼           ▼              ▼              ▼
    POST /mcp   POST /mcp/id/test  /detect     /catalog
       │           │              │              │
       ▼           ▼              ▼              ▼
   Register     Connect        Pre-add       Access
   server       & Verify       probe         filter
       │           │
       ▼           ▼
 repo_analyzer  mcp_auth
       │           │
  ┌────┼────┐      ├── credentials DB
  │    │    │      └── OAuth endpoint
  ▼    ▼    ▼
GitHub Remote Local
       │
       ▼
┌──────────────────────────────┐
│ MCPClient.connect()          │
└──────────────┬───────────────┘
               │
        ┌──────┼────────┐
        ▼      ▼        ▼
      STDIO   HTTP      SSE
        │      │        │
        └──────┼────────┘
               ▼
┌──────────────────────────────┐
│ ClientSession                │
│ initialize()                 │
│ list_tools()                 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ vendor_mcp_servers           │
│ status = VERIFIED            │
│ bound_tools = discovered     │
└──────────────────────────────┘
```

### 5.3 Application startup flow

```text
APPLICATION STARTUP

┌──────────────────────────────────────┐
│ uvicorn                              │
│ auth app OR backend app              │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Configure sys.path                   │
│ ROOT / apps/auth / apps/backend     │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Load settings                        │
│ pydantic-settings + cached singleton │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ create_app()                         │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Create FastAPI application            │
│ + CORS                               │
│ + /health                            │
│ + JWKS (auth)                        │
│ + API routers                        │
│ + vendor_resources router            │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ lifespan(app)                        │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Run Alembic migrations               │
│ in worker thread                     │
└──────────────────┬───────────────────┘
                   ▼
            ┌───────────────┐
            │ Migration OK? │
            └──────┬───┬────┘
                 Yes   No
                  │     │
                  │     ▼
                  │ ┌──────────────────┐
                  │ │ create_db_tables │
                  │ │ SQLAlchemy       │
                  │ └────────┬─────────┘
                  │          │
                  └────┬─────┘
                       ▼
┌──────────────────────────────────────┐
│ Optional: show redacted environment  │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ yield                                │
│ Application serves requests           │
└──────────────────────────────────────┘
```

### 5.4 MCP connection flow (Step 2 detail, transport-branching)

```text
MCP CONNECTION — STEP 2

┌──────────────────────────────────────┐
│ test_mcp_connection()                │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Transport self-healing               │
│ GitHub + local command + HTTP-ish    │
│ config may be forced to STDIO        │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ resolve_auth()                       │
└──────────────────┬───────────────────┘
                   ▼
             ┌──────────────┐
             │ Auth type?   │
             └──────┬───────┘
      ┌────────┬─────┼──────┬──────────┐
      ▼        ▼     ▼      ▼          ▼
    None     Basic API Key Bearer    OAuth2
      │        │     │      │          │
      ▼        ▼     ▼      ▼          ▼
   No auth   Basic  X-Key  Bearer   OAuth chain
   headers   header header header
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ 1. token cache         │
                         │ 2. refresh token       │
                         │ 3. client credentials  │
                         │ 4. dynamic registration│
                         │ 5. passthrough token   │
                         └───────────┬────────────┘
                                     ▼
┌──────────────────────────────────────────────┐
│ Build connection configuration               │
└──────────────────────┬───────────────────────┘
                       ▼
              ┌──────────────────┐
              │ MCPClient.connect │
              └─────────┬────────┘
                        │
           ┌────────────┼─────────────┐
           ▼            ▼             ▼
        ┌──────┐    ┌────────┐    ┌──────┐
        │STDIO │    │ HTTP   │    │ SSE  │
        └──┬───┘    └───┬────┘    └──┬───┘
           │            │             │
           ▼            ▼             ▼
      Prepare repo   HTTP POST    HTTP GET
      + environment               event stream
           │            │             │
           ▼            └──────┬──────┘
      Spawn process             │
           │                    │
           └──────────┬─────────┘
                      ▼
            ┌────────────────────┐
            │ ClientSession      │
            │ initialize()       │
            │ list_tools()       │
            └─────────┬──────────┘
                      ▼
            ┌────────────────────┐
            │ Persist tools      │
            │ status = VERIFIED  │
            │ Audit event        │
            └─────────┬──────────┘
                      ▼
            ┌────────────────────┐
            │ Return connection  │
            │ result             │
            └────────────────────┘
```

### 5.5 Access-filtered catalog (request/response shape)

```text
CATALOG REQUEST FLOW

┌─────────────────────────────────────┐
│ GET /catalog?q=&top_k=5             │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ get_catalog()                       │
│ + get_current_user()                │
└──────────────────┬──────────────────┘
                   ▼
             ┌─────────────┐
             │ q provided? │
             └──────┬──┬───┘
                  No│  │Yes
                    │  │
                    │  ▼
                    │ ┌─────────────────────┐
                    │ │ Semantic catalog    │
                    │ │ ranking requested   │
                    │ └──────────┬──────────┘
                    │            ▼
                    └──────►┌─────────────────────┐
                            │ Access filter FIRST  │
                            └──────────┬──────────┘
                                       ▼
                             ┌────────────────────┐
                             │ User role?         │
                             └──────┬─────────────┘
                    ┌──────────────┼───────────────┐
                    ▼              ▼               ▼
              VENDOR_ADMIN    SOLO_USER      TENANT roles
                    │              │               │
                    ▼              ▼               ▼
                All servers   is_global=true   global OR
                                               granted MCP
                    └──────────────┬──────────────┘
                                   ▼
                         ┌────────────────────┐
                         │ Candidate servers  │
                         └──────────┬─────────┘
                                    │
                         Semantic path only
                                    ▼
                         ┌────────────────────┐
                         │ embed_text(q)      │
                         └──────────┬─────────┘
                                    ▼
                            ┌──────────────┐
                            │ Embedding OK?│
                            └──────┬───┬───┘
                                 No│   │Yes
                                   │   │
                                   ▼   ▼
                         ┌─────────────┐ ┌─────────────────────┐
                         │ Return first│ │ cosine similarity   │
                         │ top_k       │ │ against embedding   │
                         └─────────────┘ └──────────┬──────────┘
                                                   ▼
                                      ┌────────────────────────┐
                                      │ CONFIRMED DEFECT        │
                                      │ VendorMCPServer has no  │
                                      │ .dim / .embedding       │
                                      │ → AttributeError        │
                                      └────────────────────────┘

Final response:
CatalogResponse { servers, count }
```

### 5.6 Component relationships (import graph, MCP subsystem)

```text
MCP SUBSYSTEM IMPORT GRAPH

                         ┌────────────┐
                         │ router.py  │
                         └─────┬──────┘
          ┌──────────┬─────────┼─────────┬──────────┬──────────┐
          ▼          ▼         ▼         ▼          ▼          ▼
      schemas   catalog_engine mcp_auth mcp_client mcp_detect repo_analyzer
                    │             │         │          │          │
                    │             │         │          │          │
                    ▼             ▼         ▼          ▼          ▼
                 models       models     MCP SDK     httpx      schemas
                    │             │
                    ▼             ▼
                Auth deps     settings
                    │
                    ▼
              Roles / CurrentUser

repo_analyzer ───────────────► mcp_detect
repo_analyzer ───────────────► schemas
repo_analyzer ───────────────► httpx / subprocess / tomllib

mcp_service
    │
    ├──► models
    ├──► schemas
    ├──► mcp_auth
    ├──► mcp_client
    ├──► mcp_detect
    ├──► repo_analyzer
    ├──► audit
    └──► Tenant model

catalog_engine ──────────────► LLMGateway.embed()

mcp_client ──────────────────► official MCP SDK
mcp_detect ──────────────────► httpx
```

**[CONFIRMED]** `repo_analyzer.py:26` imports `from github import Auth, Github` (PyGithub), but the
functions actually read (`_fetch_github_raw_manifests`, `_analyze_github_repo_normalized`) use plain
`httpx`/`subprocess.run(["git", "clone", ...])` rather than the `Github` client object.
**[UNKNOWN]** whether `Auth`/`Github` are used elsewhere in the file for a code path not exercised by
the functions read for this document (the file was read in full; no call site for `Github(...)` was
found in the content captured — **[INFERRED]** this import may be unused, but this is not stated as
confirmed dead code since re-verification against the complete file line-by-line for every branch was
not exhaustively cross-checked against the import).

### 5.7 LLM Gateway internal request flow (`complete()` / `embed()`)

```text
LLM GATEWAY

       ┌───────────────────────┐
       │ LLMGateway            │
       └───────────┬───────────┘
                   │
          ┌────────┴─────────┐
          ▼                  ▼
┌───────────────────┐  ┌────────────────────┐
│ complete()        │  │ embed()            │
│ Chat/completion   │  │ Embeddings         │
└────────┬──────────┘  └─────────┬──────────┘
         │                       │
         ▼                       ▼
┌───────────────────┐  ┌────────────────────┐
│ Build provider    │  │ Build provider     │
│ try order         │  │ try order          │
└────────┬──────────┘  │ Groq excluded      │
         │             └─────────┬──────────┘
         ▼                       ▼
┌───────────────────┐  ┌────────────────────┐
│ Optional cache    │  │ Call first provider│
└────────┬──────────┘  └─────────┬──────────┘
         │                       │
         ▼                       ▼
┌───────────────────┐       ┌──────────────┐
│ Call provider     │       │ Success?     │
└────────┬──────────┘       └──────┬───┬───┘
         │                       Yes   No
         ▼                        │     │
   ┌──────────────┐               ▼     ▼
   │ Error?       │             Return  Next provider
   └──────┬───────┘                     │
      No  │  Yes                        └──► repeat
      │   │
      ▼   ▼
   Return  ┌───────────────────────┐
           │ retryable AND         │
           │ fallback enabled?     │
           └──────┬─────────┬──────┘
                Yes         No
                 │           │
                 ▼           ▼
          Next provider    Raise error

complete():
  fallback only for retryable errors.

embed():
  fallback on ANY gateway error.
  Groq is excluded from embedding order.
```

### 5.8 Auth login → JWT issuance → protected-request flow

```text
LOGIN → JWT → PROTECTED REQUEST

┌──────────────────────────┐
│ POST /auth/login         │
│ email + password         │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ Find user in DB          │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ Verify Argon2id password │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ create_token_pair()      │
└────────────┬─────────────┘
             │
        ┌────┴─────┐
        ▼          ▼
   Access JWT   Refresh JWT
      RS256        RS256
        │          │
        └────┬─────┘
             ▼
┌──────────────────────────┐
│ Save refresh-token hash  │
│ + audit login            │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ Return tokens            │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ Protected API request    │
│ Bearer access token      │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ decode_token()           │
│ Validate JWT             │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ Load user from DB        │
└────────────┬─────────────┘
             ▼
        ┌────────────┐
        │ Tenant?    │
        └─────┬──┬───┘
            Yes  No
             │    │
             ▼    │
       ┌──────────┐│
       │ Set RLS  ││
       └────┬─────┘│
            └──┬───┘
               ▼
       ┌────────────────┐
       │ Build CurrentUser│
       └───────┬────────┘
               ▼
       ┌────────────────┐
       │ Role allowed?  │
       └──────┬────┬────┘
            No│    │Yes
              ▼    ▼
           HTTP 403  Route handler
                     executes
```

### 5.9 Docker Compose deployment topology (confirmed from `docker-compose.yml`)

```text
DOCKER COMPOSE TOPOLOGY

                         HOST MACHINE
                              │
       ┌──────────────────────┼──────────────────────────┐
       │                      │                          │
       ▼                      ▼                          ▼
   :3001                  :8001                      :8002
       │                      │                          │
       ▼                      ▼                          ▼
┌────────────┐          ┌────────────┐           ┌────────────┐
│ web        │          │ auth       │           │ backend    │
│ Next.js    │          │ FastAPI    │           │ FastAPI    │
│            │          │ port 8001  │           │ port 8002  │
└─────┬──────┘          └─────┬──────┘           └─────┬──────┘
      │                       │                          │
      │ depends on auth       │                          │
      │ healthy               │                          │
      └───────────────────────┘                          │
                                                         │
                              auth + backend share       │
                              ./data volume              │
                                                         │
                              ┌───────────────────────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │ ./data             │
                    │                    │
                    │ auth.db            │
                    │ RSA keys           │
                    └────────────────────┘


       :4000                         :6380
          │                            │
          ▼                            ▼
┌─────────────────┐           ┌─────────────────┐
│ llm-gateway     │           │ redis           │
│ FastAPI :4000   │──────────►│ redis:7-alpine  │
│ UNUSED over HTTP│ depends   │ UNUSED          │
└─────────────────┘           └─────────────────┘


       Optional :5432
             │
             ▼
      ┌─────────────────┐
      │ PostgreSQL 16   │
      │ profile=postgres│
      │ OFF by default  │
      └─────────────────┘


IMPORTANT:
• auth and backend each have their own AsyncEngine.
• Both open the same SQLite file.
• This is NOT a shared connection pool.
• llm-gateway HTTP surface is provisioned but not used by
  current application code.
• Redis is provisioned but no Python Redis client was found.
```

> `auth` and `backend` both default `DATABASE_URL=sqlite+aiosqlite:////data/auth.db` — two independent `AsyncEngine` instances (one per container) opening the **same** SQLite file, not a shared connection pool.

---

## 6. Summary — confirmed vs. inferred vs. unknown

**[CONFIRMED, high confidence — direct multi-file reading]**
- The MCP engine is client/registry-only; three transports (stdio, streamable_http, sse) via the
  official `mcp` SDK, dispatched by `MCPClient.connect()`.
- Two-step lifecycle (register → test-connection) with self-healing logic in `test_mcp_connection()`.
- Credential vault is Fernet-based, keyed off `MCP_CREDENTIALS_SECRET`/`JWT_PRIVATE_KEY`, with a
  working OAuth2 native-token-acquisition chain in `mcp_auth.py`.
- `MCPTool`/`vendor_mcp_tools` rows are now actually populated (§2.7) and ranked (§2.10) — **fixed
  this pass**, previously dead (columns existed, nothing ever wrote to them).
- A second, older MCP CRUD surface (`apps/auth/src/api/v1/mcp/`) is still mounted and live, uses a
  different `resource_type` string, and its credential manager is a non-functional stub.
- `catalog_engine.get_authorized_vendor_catalog_semantic()`'s `AttributeError` (referencing
  `.dim`/`.embedding` attributes that didn't exist on `VendorMCPServer`) is **fixed this pass** — real
  columns were added and a working hybrid (vector+BM25+rerank) ranking pipeline built on top (§2.10),
  verified against live embeddings, not just by code reading.
- The frontend's dead `agents/compile`/`agents/run` calls (404 against the running backend) are
  **fixed this pass** — `web/app/user/agents/page.tsx` now calls `GET /catalog/tools` and
  `GET /catalog/plan-tool-call` (§1.4, §2.10, §2.11), both live and verified in-browser. **The
  underlying finding this defect was a symptom of still holds without qualification**: there remains
  no code path anywhere in the repository that invokes a discovered MCP tool — everything added this
  pass is selection (§2.10) and argument-filling (§2.11) only, confirmed by design and by the absence
  of any `tools/call` invocation in the codebase (§3.6, unchanged).
- A generic OAuth "Connect via provider" authorization_code bootstrap now exists (§2.12, new this
  pass) — `mcp_auth._resolve_oauth2()`'s existing `client_credentials`/`refresh_token`/dynamic-
  registration grants had no way to obtain an *initial* refresh token for providers that require
  interactive human consent for that step; this fills only that one gap, verified against real
  Intuit/QuickBooks OAuth infrastructure (the provider correctly rejected a placeholder client_id,
  confirming the request shape itself — redirect_uri, state, scope — was well-formed).
- `apps/llm_gateway`'s `LLMGateway.complete()`/`.stream()` only fall back to the next provider on a
  **retryable** error; `.embed()` falls back on **any** error and unconditionally excludes Groq — two
  different rules, both confirmed by direct code reading and by the package's own test suite (§1.2).
  Azure OpenAI routing (`ProviderConfig.is_azure`, `LiteLLMClient._litellm_model()`/`_provider_kwargs()`)
  is new this pass — verified live against a real Azure endpoint, previously 404'd (§1.2).
- `apps/llm_gateway/api.py` is a fully standalone FastAPI service (own container, port 4000) that
  nothing else in the repository calls; the in-repo reuse of `LLMGateway` (`catalog_engine.embed_text()`,
  `tool_call_planner.plan_tool_call()`) now shares one singleton instance rather than each constructing
  its own (`llm_gateway_client.get_gateway()`, new this pass) (§1.2/§1.5).
- `docker-compose.yml` runs six services (`auth`, `web`, `redis`, `llm-gateway`, `backend`, optional
  `db`); `redis` and the `llm-gateway` container's HTTP surface are both provisioned but unused by any
  application code found in the repo (§1.5).
- `apps/auth/src/api/v1/mcp/service.py` calls `log_audit_event()` with keyword arguments
  (`event_type`, `details`) that do not exist on the actual function signature in `core/audit.py` — a
  confirmed caller/callee signature mismatch (§1.1.1).

**[INFERRED]**
- The legacy `/api/v1/mcp/*` router is unused by the shipped frontend (absence of calls in
  `web/lib/api.ts`, not a runtime trace).
- Exact behavior differences introduced by each individual recent stdio-isolation commit — reconstructed
  from current code + commit messages, not from reading each commit's diff.
- Exact validation branches inside `auth/service.refresh_tokens()`/`logout()` (token-hash comparison,
  revocation checks) — inferred from the service's overall structure and the `RefreshToken` model's
  columns, not verbatim-quoted line-by-line in this pass (§3.9).

**[UNKNOWN / not verified in this pass]**
- Whether the `log_audit_event()` signature mismatch in the legacy MCP router actually raises at
  runtime (not executed to confirm) — see §1.1.1.
- Full behavior of `web/app/vendor/page.tsx` / `web/app/vendor/tools/page.tsx` / `web/app/user/page.tsx`
  / `web/app/auth/page.tsx` beyond the endpoints they call and the child-component names they reference
  — individual component files (`login-form.tsx`, `signup-form.tsx`, `protected-dashboard.tsx`, etc.)
  were not read line-by-line for this document.
- Whether `PyGithub`'s `Github`/`Auth` classes (imported in `repo_analyzer.py`) are invoked from any
  code path not captured in the read excerpts.
- Runtime behavior of the official `mcp` SDK's internal transport implementations (treated as a
  black box; only the call sites into it were inspected).
- Exact request/response Zod-validated shapes beyond `loginSchema`/`signupSchema` (other forms in
  `web/components/*` were not individually re-verified against every backend schema field).
