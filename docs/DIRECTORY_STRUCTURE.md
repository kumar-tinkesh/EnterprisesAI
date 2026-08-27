# Directory Structure — Phase 1 (Production-Ready) & Full Project Target

> [!IMPORTANT]
> **Companion Docs:** [`SYSTEM_DESIGN.md`](doc/SYSTEM_DESIGN.md), [`PHASE1_RELEASE.md`](doc/PHASE1_RELEASE.md)  
> **Golden Rule:** Phase 1 structure is a *strict subset* of the full-project target structure. Nothing moves; components only get added as the project scales.

---

## Table of Contents

- [Part 1 — Phase 1: Full Production-Ready Structure](#part-1--phase-1-full-production-ready-structure)
  - [Phase 1 Directory Tree](#phase-1-directory-tree)
  - [Requirement to Location Traceability](#requirement-to-location-traceability)
- [Part 2 — Full Project Goal Structure ("Agent Operating System")](#part-2--full-project-goal-structure-agent-operating-system)
  - [Target Directory Tree (Delta View)](#target-directory-tree-delta-view)
  - [Evolution Rules & Architecture Safety](#evolution-rules--architecture-safety)
- [Summary](#summary)

---

## Part 1 — Phase 1: Full Production-Ready Structure

Every file below maps directly to a functional or non-functional requirement in `PHASE1_RELEASE.md`. Items marked with ⭐ are **release-blocking** core components.

### Phase 1 Directory Tree

```text
EnterpriseAI/                                   # Monorepo root
│
├── apps/
│   ├── web/                                    # Next.js 14 App Router — deployable web application
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx                        # Entry → redirect to dashboard/login
│   │   │   ├── (auth)/
│   │   │   │   ├── login/page.tsx
│   │   │   │   ├── register/page.tsx
│   │   │   │   └── oidc/callback/page.tsx      # Google OIDC round-trip
│   │   │   └── (dashboard)/
│   │   │       ├── layout.tsx                  # Sidebar + topbar shell
│   │   │       ├── agents/
│   │   │       │   ├── page.tsx                # Agent list
│   │   │       │   ├── new/page.tsx            # "Create with AI" prompt + templates gallery
│   │   │       │   └── [agentId]/
│   │   │       │       ├── page.tsx            # Canvas builder (React Flow)
│   │   │       │       ├── runs/page.tsx       # Run history + trace viewer
│   │   │       │       └── settings/page.tsx   # Versions, deploy, rollback, permissions
│   │   │       ├── knowledge/page.tsx          # KB list + upload + search playground
│   │   │       ├── connections/page.tsx        # Tool credentials management
│   │   │       ├── approvals/page.tsx          # HITL approval inbox
│   │   │       └── settings/
│   │   │           ├── members/page.tsx        # RBAC member management
│   │   │           └── profile/page.tsx
│   │   ├── components/
│   │   │   ├── canvas/
│   │   │   │   ├── AgentCanvas.tsx             # React Flow ⇄ DSL bidirectional sync
│   │   │   │   ├── nodes/                      # Custom nodes per DSL type
│   │   │   │   │   ├── TriggerNode.tsx         # Renders live execution status
│   │   │   │   │   ├── AiAgentNode.tsx
│   │   │   │   │   ├── ConditionNode.tsx
│   │   │   │   │   ├── ToolCallNode.tsx
│   │   │   │   │   ├── ApprovalNode.tsx
│   │   │   │   │   └── NotificationNode.tsx
│   │   │   │   ├── edges/
│   │   │   │   │   └── ConditionalEdge.tsx     # Labeled YES/NO/approved/rejected
│   │   │   │   └── inspector/
│   │   │   │       ├── NodeConfigForm.tsx      # Forms generated from node-type schema
│   │   │   │       └── ChatEditPanel.tsx       # Conversational editing sidebar
│   │   │   ├── runs/
│   │   │   │   ├── RunList.tsx
│   │   │   │   └── TraceViewer.tsx             # Span tree incl. cost/tokens (FR-13)
│   │   │   ├── knowledge/
│   │   │   │   ├── KbList.tsx
│   │   │   │   ├── UploadDialog.tsx
│   │   │   │   └── SearchPlayground.tsx
│   │   │   ├── approvals/
│   │   │   │   └── ApprovalCard.tsx
│   │   │   └── ui/                             # shadcn/ui primitives
│   │   ├── lib/
│   │   │   ├── api-client/                     # ⭐ Generated from core-api OpenAPI
│   │   │   ├── ws/
│   │   │   │   └── useExecutionSocket.ts       # Socket.io client + reconnect/backoff
│   │   │   ├── stores/
│   │   │   │   └── canvasStore.ts              # Zustand: graph + undo/redo history
│   │   │   └── auth.ts                         # Token handling, route guards
│   │   ├── types/                              # DSL types generated from dsl-schema pkg
│   │   ├── __tests__/
│   │   │   └── canvas.test.tsx                 # Vitest + RTL
│   │   ├── package.json
│   │   ├── next.config.mjs
│   │   ├── tailwind.config.ts
│   │   ├── tsconfig.json
│   │   ├── vitest.config.ts
│   │   ├── Dockerfile
│   │   └── .eslintrc.json
│   │
│   ├── core-api/                               # FastAPI — deployable core API service
│   │   ├── main.py                             # App factory, module router mounting
│   │   ├── config.py                           # Pydantic-settings (env-driven)
│   │   ├── db/
│   │   │   ├── base.py                         # Async engine/session + RLS session-var helper
│   │   │   └── mixins.py                       # TenantMixin (tenant_id on every model) ⭐
│   │   ├── middleware/
│   │   │   ├── auth.py                         # JWT → tenant/user context (never client-supplied)
│   │   │   ├── redaction.py                    # PII/secret log redaction
│   │   │   └── request_id.py                   # X-Request-Id propagation
│   │   ├── modules/
│   │   │   ├── iam/                            # FR-01, FR-16: Authentication & RBAC
│   │   │   │   ├── router.py                   # /auth/*, /me, members
│   │   │   │   ├── service.py
│   │   │   │   ├── repository.py
│   │   │   │   ├── models.py                   # Tenants, users, workspaces, roles
│   │   │   │   ├── schemas.py                  # Pydantic request/response
│   │   │   │   ├── rbac.py                     # require_role() dependency
│   │   │   │   └── tests/
│   │   │   ├── builder/                        # FR-02, FR-03: Prompt/NL Builder & Patcher
│   │   │   │   ├── router.py                   # /generate, /chat-edit
│   │   │   │   ├── designer.py                 # LLM NL→DSL (function-calling)
│   │   │   │   ├── patcher.py                  # Conversational graph patches + undo
│   │   │   │   ├── validator.py                # JSON Schema + semantic lint (S12)
│   │   │   │   ├── prompts/                    # Versioned prompt templates
│   │   │   │   │   ├── generate.system.j2
│   │   │   │   │   └── edit.system.j2
│   │   │   │   └── tests/
│   │   │   │       └── test_designer.py        # Golden fixtures → valid DSL
│   │   │   ├── registry/                       # FR-14: Agents CRUD, versions, deploy/rollback
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py                  # Immutable version logic (S4)
│   │   │   │   ├── repository.py
│   │   │   │   ├── models.py                   # Agents, agent_versions, deployments
│   │   │   │   └── tests/
│   │   │   ├── knowledge/                      # FR-10: RAG pipeline
│   │   │   │   ├── router.py                   # KB CRUD, upload, query
│   │   │   │   ├── ingest_worker.py            # Async ingestion consumer (S6)
│   │   │   │   ├── chunker.py                  # Unstructured-based parsing
│   │   │   │   ├── embeddings.py               # Via LiteLLM gateway
│   │   │   │   ├── retriever.py                # Hybrid vector+BM25 interface
│   │   │   │   ├── vector_repo_pgvector.py     # pgvector impl — S7 swap point ⭐
│   │   │   │   └── tests/
│   │   │   ├── tools/                          # FR-11: Connections & execution
│   │   │   │   ├── router.py                   # Connections CRUD
│   │   │   │   ├── executor.py                 # Dispatch to packages/connectors impls
│   │   │   │   └── crypto.py                   # Envelope encryption of credentials (S9) ⭐
│   │   │   ├── approvals/                      # FR-12: HITL lifecycle
│   │   │   │   ├── router.py                   # Inbox list, approve/reject
│   │   │   │   ├── service.py                  # Task creation, timeout escalation
│   │   │   │   ├── notifier.py                 # Email fan-out via provider
│   │   │   │   └── tests/
│   │   │   └── traces/                         # FR-13: Execution & trace queries
│   │   │       ├── router.py                   # /executions, /executions/{id}/trace
│   │   │       ├── repository.py
│   │   │       └── tests/
│   │   ├── migrations/                         # Alembic migrations ⭐
│   │   │   ├── env.py
│   │   │   ├── versions/
│   │   │   │   ├── 0001_initial_schema.py
│   │   │   │   └── 0002_rls_policies.py        # ⭐ Tenant isolation LIVES HERE (S3)
│   │   │   └── seeds/
│   │   │       └── seed_templates.py           # Loads templates/*.json
│   │   ├── events.py                           # Redis pub/sub publisher (node status → canvas)
│   │   ├── ws/
│   │   │   └── execution_socket.py             # WebSocket endpoint (S8)
│   │   ├── observability/
│   │   │   ├── tracing.py                      # OpenTelemetry tracing setup
│   │   │   ├── metrics.py                      # Prometheus metrics export
│   │   │   └── logging.py                      # Structured logging
│   │   ├── tests/
│   │   │   ├── conftest.py                     # Compose-backed test fixtures
│   │   │   ├── integration/
│   │   │   │   ├── test_tenant_isolation.py    # ⭐ CI-blocking gate (FR-17 / AC-12)
│   │   │   │   └── test_golden_path_api.py     # API-level golden path test
│   │   │   └── unit/
│   │   ├── pyproject.toml                      # Ruff + MyPy + Pytest config
│   │   ├── requirements.lock
│   │   ├── Dockerfile
│   │   └── .dockerignore
│   │
│   └── runtime-worker/                         # Temporal workers — deployable worker service
│       ├── worker.py                           # Bootstrap: task queues, KEDA-targeted worker
│       ├── workflows/
│       │   ├── agent_workflow.py               # ⭐ ONE generic interpreter runs any DSL
│       │   └── signals.py                      # Approval approve/reject/escalate signals
│       ├── activities/
│       │   ├── run_node.py                     # Node-type dispatcher
│       │   ├── executors/
│       │   │   ├── trigger_executor.py
│       │   │   ├── ai_agent_executor.py        # LangGraph loop inside the node
│       │   │   ├── condition_executor.py
│       │   │   ├── tool_call_executor.py       # Imports packages/connectors
│       │   │   ├── approval_executor.py        # Creates task, signal-wait (S1)
│       │   │   └── notification_executor.py
│       │   └── emit_span.py                    # Trace emission contract (S5) ⭐
│       ├── llm/
│       │   └── gateway_client.py               # LiteLLM proxy client + cost capture
│       ├── memory/
│       │   └── session_store.py                # Redis-backed session memory
│       ├── tests/
│       │   ├── test_workflow.py
│       │   └── test_retries.py
│       ├── pyproject.toml
│       └── Dockerfile
│
├── packages/                                   # Shared libraries (imported by multiple apps)
│   ├── dsl-schema/                             # ⭐ THE platform contract (S12)
│   │   ├── schema/
│   │   │   ├── agent.workflow.schema.json      # JSON Schema v1 — semver'd, never broken
│   │   │   └── examples/
│   │   │       └── employee_onboarding.json    # Golden example used by tests & prompts
│   │   ├── src/
│   │   │   └── dsl_schema/
│   │   │       ├── models.py                   # Pydantic v2 mirror of JSON Schema
│   │   │       ├── validate.py
│   │   │       └── node_types.py               # Per-node config schemas → UI form gen
│   │   ├── package.json                        # npm pkg: TS types for web (json→ts)
│   │   └── tests/
│   │       └── test_schema_examples.py
│   └── connectors/                             # Tool implementations (used by API & worker)
│       ├── src/
│       │   └── connectors/
│       │       ├── base.py                     # Protocol: manifest() + execute() + scopes
│       │       ├── http_connector/             # Generic signed HTTP/webhook
│       │       ├── slack_connector/
│       │       ├── mock_hris_connector/        # Demo data source for golden path
│       │       └── registry.py                 # Name → implementation map
│       └── tests/
│           └── test_connectors.py
│
├── infra/
│   ├── docker/
│   │   ├── docker-compose.yml                  # ⭐ Full local stack (pg+vector, redis, temporal, minio, litellm, etc.)
│   │   └── docker-compose.override.yml         # Dev hot-reload mounts
│   ├── helm/
│   │   ├── core-api/                           # Helm charts for core API
│   │   │   ├── Chart.yaml
│   │   │   ├── values.yaml
│   │   │   ├── values-staging.yaml
│   │   │   ├── values-prod.yaml
│   │   │   └── templates/
│   │   ├── runtime-worker/                     # Includes KEDA ScaledObject (S10)
│   │   │   ├── Chart.yaml
│   │   │   └── values.yaml
│   │   ├── web/                                # Helm charts for frontend web
│   │   │   ├── Chart.yaml
│   │   │   └── values.yaml
│   │   └── umbrella.yaml                       # Groups releases per environment
│   ├── terraform/
│   │   ├── modules/
│   │   │   ├── k8s_cluster/
│   │   │   ├── postgres/
│   │   │   ├── redis/
│   │   │   ├── object_storage/
│   │   │   ├── secrets/
│   │   │   └── dns_cdn/
│   │   ├── envs/
│   │   │   ├── staging/
│   │   │   │   ├── main.tf
│   │   │   │   ├── variables.tf
│   │   │   │   └── backend.tf
│   │   │   └── production/
│   │   │       ├── main.tf
│   │   │       ├── variables.tf
│   │   │       └── backend.tf
│   │   └── versions.tf
│   └── observability/
│       ├── prometheus/
│       │   ├── prometheus.yml                  # NFR alert rules
│       │   └── alerts.yml
│       ├── grafana/
│       │   └── dashboards/                     # Dashboards-as-code
│       │       ├── core-api.json
│       │       ├── runtime.json
│       │       └── knowledge.json
│       ├── loki/
│       │   └── promtail-config.yml
│       └── otel-collector-config.yaml
│
├── templates/                                  # Builtin agent templates (seeded to DB)
│   ├── employee_onboarding.json                # Golden-path template (§25 of vision)
│   ├── invoice_followup.json
│   ├── it_ticket_triage.json
│   └── README.md                               # Authoring guide + schema version tag
│
├── scripts/                                    # ⭐ Developer & CI automation
│   ├── bootstrap.sh                            # One-command dev setup (env + compose up + seed)
│   ├── seed_db.py                              # Load templates + demo tenant
│   ├── generate_api_types.sh                   # OpenAPI → TS client for web
│   ├── verify_golden_path.sh                   # Scripted AC-1…AC-11 smoke against staging
│   └── run_isolation_tests.sh
│
├── tests/
│   └── load/
│       └── k6/                                 # ⭐ NFR gates: 200 concurrent runs, KB p95
│           ├── executions.js
│           └── knowledge.js
│
├── docs/
│   ├── adr/                                    # Architecture Decision Records (S1–S12)
│   │   └── 0001-dsl-over-codegen.md
│   ├── runbook.md                              # Deploy, rollback, incident steps (DoD item)
│   ├── onboarding.md                           # New dev < 30 min guide
│   └── api.md                                  # Links to served OpenAPI docs
│
├── .github/
│   └── workflows/
│       ├── ci.yml                              # ruff+mypy → pytest → vitest → build
│       ├── cd-staging.yml                      # Merge to main → helm upgrade + smoke
│       ├── cd-production.yml                   # Manual gate → atomic upgrade + auto-rollback
│       └── security.yml                        # pip-audit, npm audit, gitleaks (weekly)
│
├── .env.example                                # ⭐ Every var, documented
├── Makefile                                    # ⭐ make dev|test|lint|migrate|seed|loadtest
├── README.md                                   # Quickstart + architecture link
├── .gitignore
├── .editorconfig
└── LICENSE
```

### Requirement to Location Traceability

| Requirement | Home in Directory Tree | Description |
|---|---|---|
| **FR-02 NL→DSL** | `apps/core-api/modules/builder/designer.py` | LLM natural language to DSL compiler |
| **FR-03 Conversational Edit** | `apps/core-api/modules/builder/patcher.py` | Graph patching and prompt revision logic |
| **FR-08 Live Canvas** | `events.py` + `ws/execution_socket.py` + `web/components/canvas/nodes/*` | Real-time WebSocket node state streaming |
| **FR-10 RAG Pipeline** | `apps/core-api/modules/knowledge/*` | Document parsing, chunking, embeddings & search |
| **FR-12 HITL Approval** | `runtime-worker/.../approval_executor.py` + `modules/approvals/` | Human-in-the-loop signal wait and approval state |
| **FR-13 Traces & Cost** | `emit_span.py` + `modules/traces/` + `web/components/runs/TraceViewer.tsx` | Execution trace tracking, token count & latency |
| **FR-17 Tenant Isolation** | `db/mixins.py` + `migrations/versions/0002_rls_policies.py` + `test_tenant_isolation.py` | PostgreSQL RLS policy and tenant isolation tests |
| **NFR Autoscaling** | `infra/helm/runtime-worker` KEDA + `tests/load/k6` | KEDA ScaledObject definition & k6 load test scripts |

---

## Part 2 — Full Project Goal Structure ("Agent Operating System")

> [!NOTE]
> **Delta View:** Everything from Part 1 stays exactly where it is. The tree below shows additions and promotions as the platform grows through Milestones M2–M4 (per `SYSTEM_DESIGN.md` §13 roadmap). Tags like `[M2]`, `[M3]` indicate when each addition is introduced.

### Target Directory Tree (Delta View)

```text
EnterpriseAI/
├── apps/
│   ├── web/                                    # + Marketplace browser, eval suites UI, cost dashboards, admin route group, multi-agent canvas (manager pattern)
│   ├── core-api/                               # PROMOTED: Modules split out into standalone services; keeps cross-module orchestration
│   │   └── modules/
│   │       └── ...                             # IAM gains SSO/SAML/SCIM; Registry gains staging+prod envs; Approvals gain SLA policies
│   ├── runtime-worker/                         # + Sub-workflows, cron/schedule triggers, multi-agent manager workflows, proactive agents
│   ├── evaluation-service/            [M2]     # Datasets, regression suites, LLM-as-judge; deploy gates wired into registry promotion
│   │   ├── src/
│   │   │   ├── router/
│   │   │   ├── services/
│   │   │   ├── judges/
│   │   │   └── runners/
│   │   └── tests/
│   ├── notification-service/          [M2]     # Promoted from approvals/notifier: email, Slack, Teams, WhatsApp fan-out
│   │   └── src/
│   │       ├── channels/
│   │       ├── templates/
│   │       └── fanout/
│   ├── marketplace-service/           [M3]     # Listings + packages (DSL+tools+KB+evals bundle)
│   │   ├── src/
│   │   │   ├── listings/
│   │   │   ├── packages/
│   │   │   ├── reviews/
│   │   │   └── install/
│   │   └── tests/
│   │       └── test_package_install.py         # Versioned install into tenant workspaces
│   ├── metering-service/              [M2]     # Token/action cost events → usage aggregation (feeds Stripe billing)
│   │   └── src/
│   │       ├── ingest/
│   │       ├── aggregation/
│   │       └── rating/
│   ├── audit-service/                 [M3]     # Dedicated append-only store, SIEM/S3 export, immutability verification jobs
│   │   └── src/
│   │       ├── ingest/
│   │       └── export/
│   ├── bff-hub/                       [M2]     # WebSocket hub + API aggregation extracted from core-api
│   │   └── src/
│   │       ├── sockets/
│   │       └── aggregators/
│   ├── admin-web/                     [M3]     # Internal ops: tenant management, feature flags, impersonation-with-audit, cost reports
│   └── e2e-tests/                     [M2]     # Playwright golden-path + isolation suites
│       └── tests/
│           └── golden-path.spec.ts
│
├── packages/
│   ├── dsl-schema/                             # v2+: loops, subflows, parallel branches, multi-agent nodes — additive & semver'd
│   │   └── schema/
│   │       └── agent.workflow.schema.v2.json
│   ├── connectors/                             # + CRM/ERP/HRIS/Jira/Gmail/QuickBooks, MCP server/client bridge (ADR-6)
│   │   └── src/
│   │       └── connectors/
│   │           └── mcp/
│   ├── sdk-python/                    [M2]     # Public developer SDK: trigger agents, fetch executions, webhook signature verification
│   │   └── enterpriseai/
│   │       ├── client/
│   │       └── models/
│   ├── sdk-typescript/                [M2]     # Same surface for JS/TS customers
│   ├── guardrails/                    [M2]     # PII redaction, topic filters, output validators
│   │   └── src/
│   │       └── guardrails/
│   │           ├── pii/
│   │           ├── topical/
│   │           └── schema_enforce/
│   └── memory/                        [M3]     # Long-term entity memory lib (mem0-style)
│
├── infra/
│   ├── helm/                                   # + Charts for every new service
│   ├── terraform/
│   │   └── envs/                               # + Multi-region (data residency), ClickHouse, Kafka, Qdrant clusters
│   │       ├── us-east-1/
│   │       ├── eu-west-1/
│   │       └── dedicated-tenant/               # Single-tenant stack packaging (enterprise tier)
│   └── observability/
│       ├── clickhouse/                         # Trace backend replaces Jaeger at scale
│       ├── opa/                                # Policy-as-code governance engine
│       │   ├── policies/*.rego
│       │   └── bundles/
│       └── kafka/
│           └── topics.yaml                     # Event backbone: metering, traces, webhooks
│
├── website/                           [M3]     # Marketing + public docs (Next.js MDX)
├── templates/                                  # Grows to full catalog (Finance/HR/Sales/IT…)
├── docs/
│   ├── adr/                                    # Continues: marketplace format, OPA, regions…
│   ├── runbooks/
│   │   └── <per-service>/
│   └── compliance/
│       ├── soc2/                               # Evidence collection structure
│       └── gdpr/
└── .github/
    └── workflows/                              # + Per-service CD pipelines, DSL contract tests between schema consumers, SDK release flows
```

### Evolution Rules & Architecture Safety

| Transition Step | How It Operates | Why It Is Architecturally Safe |
|---|---|---|
| **Module → Service** | `core-api/modules/X` folder becomes `apps/x-service`. Imports interact via standardized interfaces. | Module boundaries were strictly decoupled from day one. |
| **Jaeger → ClickHouse Traces** | Swap OpenTelemetry exporter configuration only. | Spans emitted via the `emit_span.py` contract since Phase 1. |
| **pgvector → Qdrant** | Implement existing retriever interface in a new vector repository class. | S7 repository pattern abstraction shields downstream consumers. |
| **Redis Streams → Kafka** | Publisher interface behind `events.py` remains unchanged. | Transport mechanism was never leaked to callers. |
| **New Node Types (Loops / Multi-Agent)** | Additive JSON Schema versions; existing workflows keep validating cleanly. | DSL is semver'd with golden-example regression tests. |
| **Marketplace Package Install** | A package is a bundle of existing artifacts (DSL + connector refs + KB seed + evals). | All artifact types exist from Phase 1. |
| **Multi-Region Deployment** | Terraform environment modules + per-tenant region pinning at gateway layer. | Tenant context was always explicit in request lifecycle. |

---

## Summary

- **Part 1 (Phase 1) = Build this first.** Fulfills every core requirement in `PHASE1_RELEASE.md`. Every FR/NFR maps to specific file paths, and ⭐ items are non-negotiable release blockers (migrations/RLS, isolation tests, seed scripts, `.env.example`, Makefile, k6 load tests, dashboards-as-code).
- **Part 2 (Full Goal) = Scale into this.** Zero renames or restructuring of Phase 1 code — only additive services, schema version increments, and extended packages. This ensures zero-rework evolution from MVP to Enterprise OS.
