# Enterprise AI Agent Platform — Architecture (ASCII Diagrams)

> As-built after Phases 1–3. ✅ = implemented · ⏳ = designed, deferred (seam in place).

---

## 1. PLATFORM — ALL SERVICES & COMPONENTS

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │                        EnterpriseAI/  (repo root, on sys.path)                │
 │                       pyproject.toml = SINGLE dep manifest                    │
 │                          data/auth.db = SINGLE DB                             │
 │                                                                               │
 │  ┌─────────────────────┐   ┌──────────────────────┐   ┌────────────────────┐  │
 │  │   apps/auth          │   │  apps/llm_gateway     │   │  apps/backend       │  │
 │  │   (Auth Service)     │   │  (LLM Gateway)        │   │  (Backend Service)  │  │
 │  │                      │   │                       │   │                     │  │
 │  │  ♻️ REUSED by all:   │   │  ♻️ REUSED by all:    │   │  🚀 BUILT P1–P3:    │  │
 │  │  src.db.base         │   │  LLMGateway           │   │  vendor_resources/  │  │
 │  │  src.db.session      │   │   ├ complete()        │   │   ├ models          │  │
 │  │  src.db.migrations   │   │   ├ stream()          │   │   ├ schemas         │  │
 │  │  src.core.roles      │   │   ├ embed()           │   │   ├ router          │  │
 │  │  src.core.security   │   │   └ list_models()     │   │   ├ core/vault      │  │
 │  │  src.core.audit      │   │  PromptRegistry       │   │   ├ services/       │  │
 │  │  src.api.deps        │   │   └ AGENT_COMPILER    │   │   │  ├ tool_service  │  │
 │  │  src.models.Tenant   │   │  Providers (LiteLLM)  │   │   │  ├ catalog_eng  │  │
 │  │                      │   │   ├ OpenAIClient      │   │   │  ├ embeddings   │  │
 │  │  Tables:             │   │   ├ GroqClient        │   │   │  ├ compiler     │  │
 │  │  tenants · users     │   │   └ GeminiClient      │   │   │  ├ executor     │  │
 │  │  vendor_users        │   │       └ LiteLLMClient │   │   │  └ tool_executr │  │
 │  │  workspaces          │   │          (litellm.*)   │   │   └ seed            │  │
 │  │  audit_events        │   │                       │   │                     │  │
 │  └──────────┬───────────┘   └──────────┬────────────┘   └─────────┬───────────┘  │
 │             │                          │                          │              │
 │             │       absolute imports (src.*, apps.llm_gateway.*,   │              │
 │             │       vendor_resources.*) — NO relative imports       │              │
 │             └──────────────┬───────────┴──────────────────────────┘              │
 │                            │                                                     │
 │                            ▼                                                     │
 │            ┌──────────────────────────────────────┐                              │
 │            │   SHARED SQLite DB  (data/auth.db)    │                              │
 │            │   single engine · single Alembic      │                              │
 │            │   head: d5e6f7a8b9c0                   │                              │
 │            └──────────────────────────────────────┘                              │
 └──────────────────────────────────────────────────────────────────────────────┘

 External LLM providers (via LiteLLM):
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │ OpenAI  │    │  Groq   │    │ Gemini  │
    └─────────┘    └─────────┘    └─────────┘
```

---

## 2. DATABASE — TABLES & RELATIONSHIPS

```
 ┌─────────────────────┐         ┌──────────────────────────┐
 │      tenants        │         │      vendor_tools         │
 │─────────────────────│         │──────────────────────────│
 │ id (PK, String36)   │◄──┐    │ id (PK)                  │
 │ name · slug         │   │    │ name · description       │
 │ status · is_personal│   │    │ category · method        │
 │ vendor_user_id  ─┐  │   │    │ endpoint_url (nullable)  │
 └──────────────────┼──┘   │    │ parameters_schema (JSON) │
        ▲          │       │    │ is_global · vault_sec_ref │
        │          │       │    │ created_at · updated_at   │
        │          │       │    └─────────────┬────────────┘
        │          │       │                  │ 1
        │          │       │                  │
        │          │       │                  │ 1
 ┌──────┴──────────┼───┐   │      ┌───────────┴────────────┐
 │      users       │   │   │      │    tool_embeddings      │
 │──────────────────│   │   │      │────────────────────────│
 │ id (PK)          │   │   │      │ id (PK)                 │
 │ tenant_id ───────┘   │   │      │ tool_id (FK,UNIQUE)─────┘ CASCADE
 │ email · role        │   │      │ embedding (JSON float[]) │
 │ is_active           │   │      │ model · dim              │
 └─────────────────────┘   │      └──────────────────────────┘
                           │
 ┌─────────────────────────┴────────────┐    ┌─────────────────────────────────┐
 │      tenant_resource_grants          │    │  audit_events · refresh_tokens  │
 │──────────────────────────────────────│    │  vendor_users · workspaces      │
 │ id (PK)                              │    │  workspace_members · sso_configs│
 │ tenant_id (FK tenants.id) CASCADE    │    └─────────────────────────────────┘
 │ resource_type ∈ {vendor_tool,        │
 │   mcp_server⏳, data_source⏳}        │   ⏳ = reserved seam for deferred
 │ resource_id                          │       MCP / RAG resource types
 │ UNIQUE(tenant_id, resource_type,     │
 │        resource_id)                  │
 └──────────────────────────────────────┘

 Alembic chain (single head):
 18ef1adda04f → 8eb924f12ae4 → 5b2dfbe1786e → a1b2c3d4e5f6 → b3c4d5e6f7a8
   → c4d5e6f7a8b9 (vendor_tools + grants)   [P1]
   → d5e6f7a8b9c0 (tool_embeddings)         [P2]  ← HEAD
```

---

## 3. LLM GATEWAY — LiteLLM ROUTING & FALLBACK

```
                         ┌──────────────────────────────┐
                         │         LLMGateway            │
                         │  (router + fallback + cache   │
                         │   + ⧖ reasoning extraction)   │
                         │                              │
                         │  complete() stream() embed()  │
                         │  list_models() from_env()     │
                         └──────────────┬───────────────┘
                                        │ picks provider
                                        ▼
         ┌─────────────────────────────────────────────────────┐
         │           providers/litellm_client.py                │
         │              LiteLLMClient(BaseLLMClient)             │
         │                                                    │
         │  litellm.acompletion()   litellm.aembedding()        │
         │  model prefix: "openai/" "groq/" "gemini/"           │
         │  response_format / tools passthrough                 │
         │  exception map → gateway hierarchy (retryable flags) │
         └────────────────────┬────────────────────────────────┘
                              │ thin subclasses (names preserved)
   ┌──────────────┬───────────┼──────────────┬──────────────┐
   ▼              ▼           ▼              ▼              ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│OpenAICli│  │GroqClien│  │GeminiCli│   _PASS_API_BASE:
│ PREFIX  │  │ PREFIX  │  │ PREFIX  │     openai=T groq=T
│"openai/"│  │"groq/"  │  │"gemini/"│     gemini=F (native)
│embed: ✓ │  │embed: ✗ │  │embed: ✓ │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     └────────────┴────────────┘
                  │
                  ▼
            ┌─────────────────────────┐
            │      litellm (lib)       │
            └─────┬───────┬───────┬────┘
                  ▼       ▼       ▼
              ┌──────┐ ┌──────┐ ┌──────┐
              │OpenAI│ │ Groq │ │Gemini│
              └──────┘ └──────┘ └──────┘

 Fallback order (on retryable error):
   openai → [gemini, groq]      groq → [openai, gemini]      gemini → [openai, groq]
 Embeddings skip groq (EMBEDDINGS_SUPPORTED=False).
```

---

## 4. ACCESS CONTROL — THREE-TIER MODEL

```
                       ┌──────────────────────────────┐
                       │    GLOBAL VENDOR CATALOG      │
                       │      (vendor_tools)           │
                       └───────────────┬──────────────┘
                                       │
                  ┌────────────────────┴────────────────────┐
                  ▼                                         ▼
        ┌──────────────────┐                    ┌──────────────────────┐
        │    SOLO USER      │                    │  TENANT ORGANIZATION  │
        │ (direct access)   │                    │ (resource grants)     │
        └────────┬──────────┘                    └───────────┬──────────┘
                 │                                           │
                 ▼                                           ▼
        is_global == True                       is_global == True
                 │                            OR  id ∈ tenant_resource_grants
                 │                                           │
                 └───────────────────┬───────────────────────┘
                                     ▼
                       ┌──────────────────────────────┐
                       │ get_authorized_vendor_catalog │
                       │    (db, user) → list[Tool]    │
                       │   ── the ONE access filter ── │
                       └──────────────┬───────────────┘
                                      │ reused by
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
         GET /catalog        semantic matcher          AI compiler
         (access-filter)     (rank candidates)        (stages 1–2)

 Roles (src.core.Roles — string constants, not Enum):
   VENDOR_ADMIN · TENANT_ADMIN · TENANT_USER · SOLO_USER
 Guards (src.api.deps):  get_current_user()  ·  require_roles(*roles)
```

---

## 5. VENDOR RESOURCES — MODULE LAYERS & DEPENDENCIES

```
                          ┌─────────────────────────────────────────────┐
                          │                 router.py                    │
                          │   (only module that knows FastAPI/HTTP)      │
                          │  /tools /catalog /grants /agents/* /{id}     │
                          └──────┬──────────┬──────────┬──────────┬──────┘
                                 │          │          │          │
                      ┌──────────▼──┐  ┌────▼─────┐  ┌─▼────────┐ ┌▼──────────┐
                      │tool_service │  │catalog_  │  │compiler  │ │(grants/   │
                      │  .py        │  │engine.py │  │.py       │ │ delete)   │
                      │ CRUD+grants │  │ access + │  │ stages   │ └───────────┘
                      │ embed-create│  │ semantic │  │  3 & 4   │
                      └──┬──────┬───┘  └────┬─────┘  └────┬─────┘
                         │      │           │             │
              ┌──────────▼┐  ┌──▼───────────▼─────────────▼──┐
              │executor.py │  │      embeddings.py            │  ← sole gateway
              │ (LangGraph)│  │ get_gateway() (lru_cache)     │    construction
              └──────┬─────┘  │ embed_text() · cosine()       │    point
                     │        └──────────────┬────────────────┘
              ┌──────▼─────┐                  │
              │tool_executr│                  │
              │  .py       │                  ▼
              │ httpx/sim  │          ┌──────────────────┐
              └──────┬─────┘          │ LLMGateway.from_  │
                     │                │   env()           │
                     ▼                └──────────────────┘
              ┌────────────┐
              │tool_service│   schemas.py  ◄── used by router/compiler/executor
              │ .get_tool  │   models.py   ◄── used by all services
              └─────┬──────┘   core/vault.py ◄── tool_service (AES secret ref)
                    │
                    ▼
              src.db.session.get_db  (shared async engine)
              src.api.deps · src.core.roles · src.core.audit · src.models.Tenant

 Layering rules:
   · services are framework-free (testable w/ bare AsyncSession)
   · embeddings.py is the ONLY place an LLMGateway is built
     → patch one symbol to neutralise/replace all LLM I/O in tests
   · models.py / schemas.py depend on nothing but Base / Pydantic
```

---

## 6. AI COMPILER PIPELINE — NL → CompiledAgentSpec

```
  POST /agents/compile   { query, top_k }        Authorization: Bearer <JWT>
                          │
                          ▼
                 get_current_user → CurrentUser{role, tenant_id}
                          │
                          ▼
  ┌────────────────────────────────────────────────────────────────────────────┐
  │                          compile_agent(db, user, query, top_k)              │
  │                                                                            │
  │  STAGE 1 — ACCESS FILTER            STAGE 2 — SEMANTIC MATCH               │
  │  ┌──────────────────────────┐       ┌──────────────────────────────┐       │
  │  │get_authorized_vendor_    │──────►│embed_text(query) → q_vec      │       │
  │  │  catalog(db, user)        │       │load tool_embeddings          │       │
  │  │ role/tenant → list[Tool]  │       │skip if no emb or dim mismatch│       │
  │  └──────────────────────────┘       │cosine rank → top_k           │       │
  │         (unranked)                  └──────────────┬───────────────┘       │
  │                                                     ▼                      │
  │                                          candidates: list[Tool]             │
  │                                                     │                      │
  │  empty? ──────────────────────► exit A: empty_spec (nodes:[])               │
  │                                                     │                      │
  │  STAGE 3 — SCHEMA SHRINK                          ▼                      │
  │  ┌──────────────────────────┐    ┌──────────────────────────────────┐      │
  │  │ shrink_schema(params)    │◄───│ catalog = [{id,name,desc,method, │      │
  │  │ drop description/$comment│    │   parameters_schema(shrunk)}…]   │      │
  │  │ /title/examples          │    └──────────────────────────────────┘      │
  │  └──────────────────────────┘                                              │
  │                                                     │                      │
  │  STAGE 4 — STRUCTURED SPEC GENERATION              ▼                      │
  │  ┌──────────────────────────────────────────────────────────────┐         │
  │  │ prompt = PromptRegistry.format(AGENT_COMPILER,               │         │
  │  │           nl_request=query, available_tools=catalog)          │         │
  │  │ req = CompletionRequest(messages=[SYS+USER],                  │         │
  │  │       response_format={"type":"json_object"}, temp=0.2)       │         │
  │  │ resp = get_gateway().complete(req)  → content = "<json>"      │         │
  │  │   │ (via LiteLLM → OpenAI/Groq/Gemini)                        │         │
  │  │   ▼                                                            │         │
  │  │ _parse_spec: json.loads → CompiledAgentSpec.model_validate    │         │
  │  │   │  None? ──retry once (append error)──► still None?         │         │
  │  │   │                                       yes → exit B:       │         │
  │  │   │                                            fallback_spec   │         │
  │  │   ▼                                            (top candidate) │         │
  │  │ _validate_tool_ids(spec, allowed={tool ids}):                 │         │
  │  │   tool_id ∉ allowed → tool_id=None, unconfigured=True         │         │
  │  │   (defense-in-depth — LLM can't bind unauthorized tools)      │         │
  │  └────────────────────────────┬─────────────────────────────────┘         │
  │                               ▼                                            │
  │                        exit C: CompiledAgentSpec                            │
  └────────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
  ┌────────────────────────────────────────────────────────────────────────────┐
  │                       CompiledAgentSpec (Pydantic v2)                       │
  │   agent_name · description                                                 │
  │   nodes: [ AgentNode{ id, tool_id, node_type, args, unconfigured } ]        │
  │   edges: [ AgentEdge{ source, target, condition? } ]        (extra="allow") │
  └────────────────────────────────────────────────────────────────────────────┘

  EXITS:  A empty catalog  ·  B LLM unavailable/unreliable → linear fallback  ·  C happy path
  Invariant: compile_agent NEVER raises on LLM misbehaviour.
```

---

## 7. LANGGRAPH EXECUTOR — DAG → StateGraph → results

```
  POST /agents/run  { query, top_k }
         │
         ▼
   spec = compile_agent(...)          (see §6)
         │
         ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                     execute_spec(db, spec)                        │
  │                                                                  │
  │  [1] _topo_order(nodes, edges)  ── Kahn's algorithm              │
  │      in-degree 0 → queue (declaration-order tiebreak)            │
  │      cycle / unknown nodes / mismatch → fallback declaration     │
  │      → order: [n0, n1, n2, …]   (never deadlocks)                │
  │                                                                  │
  │  [2] graph = StateGraph(AgentState)                              │
  │      add_node(nid, callable)  for each                           │
  │      add_edge(START → order[0])                                  │
  │      add_edge(order[i] → order[i+1])  …                          │
  │      add_edge(order[-1] → END)                                   │
  │                                                                  │
  │      AgentState (TypedDict, reducer-backed):                     │
  │        query:  str                                               │
  │        results: Annotated[dict,  _merge_dict]                    │
  │        trace:   Annotated[list,  _merge_list]                    │
  │                                                                  │
  │  [3] app = graph.compile()                                       │
  │  [4] final = await app.ainvoke({query:"", results:{}, trace:[]}) │
  └──────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  per-node callable:                                         │
   │    result = await invoke_tool(db, node, state)  (see §8)    │
   │    return { results:{node.id: result},                       │
   │             trace:[{node, node_type, result}] }              │
   │                          │                                   │
   │           reducers merge delta into running state            │
   └─────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
   RunAgentResponse { spec, results: {node_id → result}, trace: [...] }
```

### State evolution (2-node example, endpoint-less tools)

```
 state0: { results:{},                     trace:[] }
              │  START → n1
              ▼
 n1.invoke_tool → R1 (simulated) ; returns delta {results:{n1:R1}, trace:[n1]}
 state1: { results:{n1:R1},                  trace:[n1] }      ← merged
              │  n1 → n2
              ▼
 n2.invoke_tool → R2 (simulated) ; returns delta {results:{n2:R2}, trace:[n2]}
 state2: { results:{n1:R1, n2:R2},           trace:[n1,n2] }   ← merged
              │  n2 → END
              ▼
 final:  { results:{n1:R1, n2:R2},           trace:[n1,n2] }
```

---

## 8. TOOL EXECUTION — invoke_tool decision tree

```
   node
    │
    ▼
  tool_id is None  OR  unconfigured ? ── yes ──► {simulated:True, "no tool bound"}
    │ no
    ▼
  tool = get_tool(db, tool_id)
  tool is None ? ───────────────── yes ──► {simulated:True, "tool not found"}
    │ no
    ▼
  endpoint_url is None ? ───────── yes ──► {simulated:True, tool, method, args,
    │ no                                    "no endpoint configured"}
    ▼
  httpx.AsyncClient.request(method, endpoint_url, json=args)
    │
    ├─ success ──► {simulated:False, tool, status:code, body: json|{text}}
    └─ exception ► {simulated:False, tool, error:str(exc)}    ← never raises

  Seeded defaults:  notification.sendEmail · hr.lookupEmployee · finance.getInvoice
                   (all endpoint_url=None → simulated, so DAGs run w/o external APIs)

  ⏳ vault_secret_ref injection (auth headers from vault) — deferred
```

---

## 9. SEMANTIC MATCHING — embeddings + cosine

```
   TOOL CREATE / POST /tools/{id}/embed
        │
        ▼
   embed_tool_text(tool)  →  embed "{name}\n{description}"
        │   (best-effort: no provider → None → tool still created, no embedding)
        ▼
   ┌─────────────────────────────────────┐
   │ tool_embeddings                     │
   │  tool_id (UNIQUE) · embedding (JSON │
   │  list[float]) · model · dim         │
   └─────────────────────────────────────┘

   QUERY  (GET /catalog?q=  or  compile_agent)
        │
        ▼
   ┌──────────────────────────────────────────────────────┐
   │ get_authorized_vendor_catalog_semantic(db,user,query)│
   │                                                      │
   │  1. access filter FIRST  → candidates  (§4)          │
   │  2. embed_text(query) → q_vec  (same gateway default)│
   │  3. load candidates' tool_embeddings                 │
   │  4. for each candidate:                              │
   │       skip if emb is None OR emb.dim != len(q_vec)   │
   │       score = cosine_similarity(q_vec, emb.embedding)│
   │  5. sort desc → top_k                                │
   │                                                      │
   │  fallback: no embeddings / no q_vec → access-filter  │
   │            list truncated to top_k (never raises)    │
   └──────────────────────────────────────────────────────┘
        │
        ▼
   ranked list[VendorTool]

   cosine_similarity(a,b) = dot(a,b) / (‖a‖·‖b‖)
        → 1.0 identical · 0.0 orthogonal · 0.0 on length-mismatch / zero-vec
   Storage = portable JSON → swappable to pgvector / sqlite-vec later
```

---

## 10. REQUEST LIFECYCLE — end-to-end (POST /agents/run)

```
  Client
    │  POST /agents/run  {"query":"verify a vendor invoice over 5000","top_k":5}
    │  Authorization: Bearer <JWT>
    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  apps/backend/main.py  (FastAPI)                                │
  │   lifespan: run_migrations() [thread] → seed_defaults()         │
  │   CORS · /health · mount vendor_resources router                │
  └────────────────────────────┬────────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  router.run_agent_endpoint                                      │
  │    get_current_user(JWT) ─► CurrentUser{role, tenant_id}        │
  │    get_db ─► AsyncSession                                       │
  └────────────────────────────┬────────────────────────────────────┘
                               ▼
  ┌─────────────── COMPILE (§6) ───────────────┐   ┌─── LLM (§3) ───┐
  │ access filter → semantic → shrink schema   │◄──┤ gw.complete()  │
  │ → AGENT_COMPILER prompt → complete()        │   │ via LiteLLM    │
  │ → validate (tool_id authz) → CompiledAgentSpec                 │
  └────────────────────────────┬───────────────┘   └────────────────┘
                               ▼
  ┌─────────────── EXECUTE (§7) ──────────────┐   ┌── tools (§8) ──┐
  │ _topo_order → StateGraph → ainvoke         │──►│ invoke_tool    │
  │ per node: invoke_tool → merge results/trace│   │ httpx / sim    │
  └────────────────────────────┬───────────────┘   └────────────────┘
                               ▼
  RunAgentResponse { spec, results: {node_id→result}, trace: [...] }
                               │
                               ▼
  Client  ◄────────────────────┘   200 OK
```

---

## 11. MCP SERVERS & KNOWLEDGE BASES — deferred, seam in place ⏳

```
  EXISTING SEAMS (already built, reused by future resource types):

   tenant_resource_grants.resource_type ∈ {vendor_tool, mcp_server⏳, data_source⏳}
        │
        ├─► vendor_tools          ✅ (built)
        ├─► vendor_mcp_servers    ⏳ (new table + mcp_service.py + MCP SDK)
        └─► vendor_data_sources   ⏳ (new table + datasource_service.py + pypdf)

  compiler.node_type ∈ {tool.call, logic.condition, notification.send, ai.agent,
                        rag.retrieve⏳, mcp.call⏳}    ← arbitrary strings accepted

  tool_executor.invoke_tool dispatch ─► httpx (tool.call)
                                     ─► MCP transport ⏳ (mcp.call)
                                     ─► retrieval ⏳     (rag.retrieve)

  ┌──────────────────────────────────────────────────────────────────────┐
  │  PLUG-IN RECIPE (additive — no re-architecture):                    │
  │                                                                      │
  │  MCP SERVER                          RAG KNOWLEDGE BASE               │
  │  ───────────                         ──────────────────              │
  │  1. VendorMCPServer model            1. VendorDataSource model       │
  │  2. migration                        2. migration                    │
  │  3. grant_resource accepts "mcp"     3. grant_resource accepts "ds"  │
  │  4. catalog includes MCP servers     4. catalog includes data srcs   │
  │  5. (opt) embed discovered tools     5. pypdf→chunk→embed→chunks tbl │
  │  6. compiler prompt: "mcp.call"      6. compiler prompt: "rag.retrieve"
  │  7. invoke_tool: MCP transport       7. invoke_tool: cosine retrieve │
  │  8. schemas + CRUD routes            8. schemas + CRUD routes        │
  │                                                                      │
  │  Steps 1–4,8 mechanical · 5–7 reuse embeddings/cosine/compiler/      │
  │  executor machinery already in place.                                │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## 12. ASYNC / CONCURRENCY MODEL

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  Event loop (uvicorn, single process)                              │
  │                                                                    │
  │  Request ──► get_db() ──► AsyncSession (aiosqlite, expire_on_      │
  │            commit=False)        ──► service (await) ──► commit/     │
  │                                                     rollback        │
  │                                                                    │
  │  LLMGateway (lru_cache, 1/process)                                 │
  │     gw.complete()/embed()  ──await──►  litellm.acompletion()        │
  │                                       (httpx async, fallback+cache)│
  │                                                                    │
  │  Executor: graph.ainvoke() — nodes in topo order, sequential       │
  │     node callable: await invoke_tool (httpx async, non-blocking)   │
  │     coordination = reducer-backed AgentState (no shared mutables)  │
  │                                                                    │
  │  Startup lifespan:                                                 │
  │     run_migrations() ──asyncio.to_thread──► worker thread (Alembic)│
  │        on failure → await create_db_tables()                       │
  │     seed_defaults() — idempotent                                   │
  │                                                                    │
  │  No background workers / queues — compile & run are sync req/resp. │
  └────────────────────────────────────────────────────────────────────┘
```

---

## 13. CONFIGURATION SURFACE

```
  ENVIRONMENT VARIABLES
  ─────────────────────
  Database / Auth (shared):
    DATABASE_URL            = sqlite+aiosqlite:///./data/auth.db   # → postgresql+asyncpg://…
    DB_ECHO                 = false
    JWT_*                   = (Auth RS256 — reused by get_current_user)

  LLM Gateway (LiteLLM):
    OPENAI_API_KEY          =
    GROQ_API_KEY            =
    GEMINI_API_KEY          =
    OPENAI_EMBEDDING_MODEL  = text-embedding-3-small
    LLM_GATEWAY_DEFAULT_PROVIDER  = openai      (completions)
    LLM_GATEWAY_EMBEDDING_PROVIDER= gemini       (embeddings)
    LLM_GATEWAY_TIMEOUT     = 60
    LLM_GATEWAY_MAX_RETRIES = 3
    LLM_GATEWAY_ENABLE_CACHE= false
    LLM_GATEWAY_CACHE_TTL   = 3600

  Backend / Vendor Resources:
    VENDOR_VAULT_KEY        = <32-byte urlsafe-b64>   # empty → dev-only derived key
    BACKEND_API_V1_PREFIX   = /api/v1

  Generate a vault key:
    uv run python -c "from vendor_resources.core.vault import generate_key; print(generate_key())"
```

---

## 14. RUN & TEST

```
  Run backend:      uv run uvicorn apps.backend.main:app --reload --port 8002
                   GET /health → {"status":"ok","service":"backend"}
                   /docs       → OpenAPI incl. /api/v1/vendor/resources/*

  Migrate:          uv run alembic upgrade head      # from repo root
                   uv run alembic current            # → d5e6f7a8b9c0 (head)

  Tests:            uv run pytest                    # full suite (136)
                   uv run pytest apps/backend/vendor_resources/tests
                   uv run pytest apps/llm_gateway/tests

  Test isolation:   isolated temp SQLite engine · get_db overridden per app
                   mock_gateway / mock_llm = deterministic keyword→vector
                   embed + canned compiler JSON (no network, no API keys)
                   executor simulation path → LangGraph runs w/o external APIs
```

---

## 15. ROADMAP (deferred)

```
  ⏳ 1. RAG Knowledge Bases    — vendor_data_sources + chunks + pypdf + retrieval
  ⏳ 2. MCP Servers            — vendor_mcp_servers + MCP SDK + auto-discovery
  ⏳ 3. Conditional/parallel   — add_conditional_edges using edge.condition
  ⏳ 4. json_schema output     — stricter per-provider structured output
  ⏳ 5. Guardrail/approval     — gate destructive methods on /agents/run
  ⏳ 6. vault_secret_ref       — inject auth headers into real tool calls
  ⏳ 7. Compiled-agent persist — compiled_agents table + re-run endpoint
  ⏳ 8. Postgres + pgvector    — change DATABASE_URL + vector column type
```

```
  Legend:  ✅ built   ⏳ designed/deferred   ♻️ reused   🚀 new (P1–P3)
```