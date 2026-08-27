# Phase 1 Release — Enterprise AI Agent Platform

> **Release Codename:** `M1-GoldenPath`
> **Based on:** `PRODUCT_VISION_AGENTS.pdf` (§25 First Prototype) + `SYSTEM_DESIGN.md`
> **Status:** Release Plan v1.0
> **Duration:** ~8 weeks (2-week sprints × 4)
> **Guiding rule:** *Prototype now, scale later — but never rewrite.* Every choice below is production-shaped from day one.

---

## Table of Contents

1. [Release Goal](#1-release-goal)
2. [Scope](#2-scope)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements (Scalability Targets)](#4-non-functional-requirements)
5. [Phase 1 Architecture](#5-phase-1-architecture)
6. [Tech Stack (with Versions)](#6-tech-stack-with-versions)
7. [Core Data Model](#7-core-data-model)
8. [API Surface](#8-api-surface)
9. [Built-in Scalability Decisions](#9-built-in-scalability-decisions)
10. [Environments & Deployment](#10-environments--deployment)
11. [Delivery Milestones](#11-delivery-milestones)
12. [Acceptance Criteria (Golden Path Demo)](#12-acceptance-criteria-golden-path-demo)
13. [Risks & Mitigations](#13-risks--mitigations)

---

## 1. Release Goal

Prove the core product experience end-to-end with the **Employee Onboarding Agent** golden path:

```
Describe → Design → Edit → Connect → Test → Approve → Deploy → Watch Live Trace
```

…while shipping on an infrastructure that scales horizontally without architectural rework.

**Success = one sentence:** A new user types *"Create an employee onboarding agent"*, sees the generated workflow on a canvas, modifies it conversationally and visually, connects tools + HR knowledge, tests it, approves through a human step, deploys it, and watches a live traced execution — with cost and latency shown.

## 2. Scope

### ✅ In Scope

| Area | Deliverable |
|---|---|
| Auth | Email/password + Google OIDC login; single workspace per user; basic roles (Admin/Editor/Viewer) |
| Multi-tenancy | Tenant schema + RLS enforced everywhere (even if UI creates only one tenant per signup) |
| Agent Builder | NL → Workflow DSL generation; conversational patching ("add manager approval before creating record"); template library (3 templates) |
| Visual Builder | React Flow canvas ⇄ DSL bidirectional sync; node config forms; drag/connect/delete |
| Node Types | `event.trigger` (manual/webhook), `ai.agent`, `logic.condition`, `tool.call`, `human.approval`, `notification.send` |
| Runtime | Temporal-based durable execution; retries with backoff; live node status streaming |
| Knowledge | KB CRUD; PDF/TXT/DOCX upload → chunk → embed → hybrid retrieve (pgvector) |
| Tools | HTTP/Webhook connector, Slack send connector, mock HRIS connector (for demos); credential store (encrypted) |
| HITL Approval | In-app approval inbox + email notification; timeout → escalate to admin; approve/reject paths |
| Observability | Per-node execution trace viewer; token/cost per LLM call; run history list |
| Versioning & Deploy | Draft → version snapshot → "Deploy"; rollback to previous version |
| Testing | Manual test-run panel with sample input; run result diff view |

### ❌ Out of Scope (deferred to M2+)

- Marketplace publish/install
- Multi-agent (manager pattern) orchestration
- SSO/SAML/SCIM, granular OPA policy engine (basic RBAC only)
- Staging vs production environments (single deploy target; versioning + rollback included)
- Scheduled triggers / cron
- Billing/metering dashboards (cost is logged, not billed)
- Native connectors beyond Slack/HTTP/mock-HRIS
- Mobile/responsive canvas

---

## 3. Functional Requirements

| ID | Requirement | Priority | Acceptance |
|---|---|---|---|
| FR-01 | User signs up / logs in (email + Google OIDC) | P0 | JWT session; tenant + workspace auto-created |
| FR-02 | "Create with AI": prompt → valid DSL draft on canvas in < 30s | P0 | Draft passes JSON Schema validation; only references connected tools |
| FR-03 | Conversational edit: instruction → graph patch applied & revalidated | P0 | Undo/redo history works; invalid patch rejected with explanation |
| FR-04 | Visual edit: add/remove/connect/configure nodes on canvas | P0 | Canvas changes serialize back to valid DSL |
| FR-05 | Node config forms generated from node-type schemas | P1 | No free-form JSON editing required for standard nodes |
| FR-06 | Templates: Employee Onboarding, Invoice Follow-up, IT Ticket Triage | P1 | Template installs as editable draft |
| FR-07 | Manual test run: provide input → execute → view per-node results | P0 | Run visible in run history with status |
| FR-08 | Live execution: canvas nodes animate pending→running→success/fail | P0 | Status updates arrive < 1s after node transition (WebSocket) |
| FR-09 | `ai.agent` node: LLM call with system prompt, output schema, optional KB retrieval | P0 | Structured output enforced; tokens+cost recorded per call |
| FR-10 | Knowledge base: upload PDF/DOCX/TXT → searchable within 60s for 20-page doc | P0 | Retrieved chunks cited in ai.agent trace |
| FR-11 | Tool call via connector with encrypted credential | P0 | Secrets never appear in DSL, logs, or traces |
| FR-12 | Human approval: pauses run, notifies approver, resumes on decision | P0 | Approve/reject paths both work; timeout (configurable) escalates |
| FR-13 | Execution trace: full span tree incl. prompts, retrievals, tool I/O, cost | P0 | Answers all 10 trust questions from vision doc |
| FR-14 | Version snapshot + deploy + rollback | P0 | Deployed version immutable; rollback restores previous pointer < 5s |
| FR-15 | Webhook trigger: external POST starts deployed agent | P1 | Signed webhook; rejects unsigned requests |
| FR-16 | RBAC basics: Viewer sees, Editor edits/runs, Admin deploys/manages members | P1 | Enforced server-side, not just UI |
| FR-17 | Tenant isolation: user A can never read tenant B's agents/knowledge/runs | P0 | Verified by automated isolation tests |

## 4. Non-Functional Requirements

**Phase 1 load profile:** design for **50 tenants / 500 users / 10k executions per month**, but *architect* so the same code serves 100× by adding replicas — not rewrites.

| Attribute | Phase 1 Target | Scaling Mechanism |
|---|---|---|
| API latency (p95) | < 300ms (non-LLM endpoints) | Stateless FastAPI pods → HPA on CPU/RPS |
| NL generation time | < 30s p95 | Async job pattern; streamed to UI; LLM gateway timeout budget |
| Canvas live-status lag | < 1s | Redis pub/sub fan-out; horizontal WS hub pods |
| Concurrent executions | 200 simultaneous | Temporal workers scale on task-queue depth (KEDA) |
| Long-running runs | Survive pod restarts & deploys | Durable state in Temporal, not worker memory |
| Approval wait | Up to 7 days without resource use | Temporal signal-wait (zero CPU while waiting) |
| Knowledge query (p95) | < 800ms for ≤ 100k chunks | pgvector HNSW index; connection pooling (pgbouncer) |
| Availability | 99.5% (single region) | Multi-replica all stateless services; managed DBs with HA |
| Trace completeness | 100% of executions | Emission is part of the runtime contract, not optional logging |
| Security baseline | OWASP Top 10 pass; secrets encrypted at rest (AES-256-GCM envelope via KMS/Vault) | Automated dependency scanning in CI |
| Data durability | RPO ≤ 15 min | Postgres PITR + daily snapshots to object storage |

---

## 5. Phase 1 Architecture

Simplified from the full design: **3 deployables + platform data**, with module boundaries that split cleanly in M2.

```
                        ┌─────────────────────────────┐
                        │   Web App (Next.js on Vercel│
                        │        or Nginx pod)        │
                        └──────────────┬──────────────┘
                                       │ HTTPS / WSS
                          ┌────────────▼────────────┐
                          │   Traefik API Gateway   │
                          └──┬─────────┬─────────┬──┘
                             │         │         │
              ┌──────────────▼──┐ ┌────▼─────────▼───────┐
              │  core-api       │ │  runtime-worker      │
              │  (FastAPI)      │ │  (Temporal workers)  │
              │  ┌───────────┐  │ │  executes Workflow   │
              │  │ IAM       │  │ │  DSL graphs durably  │
              │  │ Builder   │  │ └──────┬───────────────┘
              │  │ Registry  │  │        │ calls at runtime
              │  │ Knowledge │  │        ▼
              │  │ Tools     │◄─┼────────┘ (tool exec, KB retrieve,
              │  │ Approvals │  │          LLM via gateway, notify)
              │  └───────────┘  │
              └───────┬─────────┘
                      │
   ┌──────────────────▼───────────────────────────────────────┐
   │                PLATFORM DATA LAYER                        │
   │  PostgreSQL 16 (+pgvector, +RLS) · Redis 7 · S3/MinIO     │
   └───────────────────────────────────────────────────────────┘
                      │
        ┌─────────────┼──────────────────┐
        ▼             ▼                  ▼
  Temporal Server   LiteLLM Gateway   SMTP/Email provider
  (durable exec)    (OpenAI etc.)     (approvals, invites)
```

**Deployable units:**

| Unit | Contains | Scaling |
|---|---|---|
| `web` | Next.js app | CDN/static; stateless pods |
| `core-api` | IAM, Builder Service, Workflow Registry, Knowledge Service, Tool Service, Approval Service, trace query API — as **separate Python modules** behind one FastAPI app | Stateless; HPA replicas |
| `runtime-worker` | Temporal workers interpreting deployed DSL | KEDA autoscale on Temporal queue depth |

**Key rule:** `core-api` and `runtime-worker` are **separate deployments** from day one — builder deploys never interrupt running agents.

---

## 6. Tech Stack (with Versions)

### Frontend

| Tech | Version | Purpose | Scalability Note |
|---|---|---|---|
| Next.js (React) | 14.x | App framework (App Router) | Static export/ISR for shell; API routes avoided (backend is separate) |
| TypeScript | 5.x | Type safety | Strict mode |
| React Flow (@xyflow/react) | 12.x | Visual canvas | Virtualized rendering handles 100+ node graphs |
| Tailwind CSS | 3.4.x | Styling | — |
| shadcn/ui + Radix | latest | Accessible components | — |
| TanStack Query | 5.x | Server-state cache | Optimistic updates for canvas edits |
| Zustand | 4.x | Canvas/local UI state | — |
| socket.io-client | 4.7.x | Live execution status | Reconnect + backoff built-in |

### Backend

| Tech | Version | Purpose | Scalability Note |
|---|---|---|---|
| Python | 3.12.x | All backend services | — |
| FastAPI | 0.115.x | REST APIs | Async; stateless → horizontal scale |
| Pydantic v2 | 2.x | DSL schema & settings validation | Rust-core validation speed |
| Temporal Python SDK | 1.8.x+ | Durable workflow execution | Workers are stateless consumers → KEDA scale |
| SQLAlchemy 2 + Alembic | 2.x / 1.13.x | ORM + migrations | Async engine; pgbouncer pooling |
| asyncpg | 0.29.x | Postgres driver | Pool per pod |
| pgvector | 0.7.x | Vector search in Postgres | HNSW index; swap-out interface defined |
| Redis (redis-py) | 7.2 / 5.x client | Pub/sub, cache, rate limit | Managed Redis; cluster-ready config |
| httpx | 0.27.x | Outbound connector HTTP | Async, pooled |
| LiteLLM | 1.4x.x | LLM gateway/proxy | Separate deployment; budget caps, fallbacks |
| Unstructured | 0.15.x | PDF/DOCX parsing | Runs as ingestion job (queue worker) |
| OpenTelemetry SDK | 1.2x.x | Tracing instrumentation | OTLP → collector (Jaeger dev, vendor later) |
| python-jose / passlib | latest | JWT + password hashing | Argon2id |
| cryptography | 42.x | Envelope encryption for credentials | KMS/Vault root key |

### Infrastructure

| Tech | Version | Purpose |
|---|---|---|
| Docker + Compose | 24.x / 2.2x | Local dev parity (`docker compose up` full stack) |
| Kubernetes | 1.29+ (managed: EKS/GKE/DOKS) | Prod runtime |
| Helm | 3.x | Packaging our services |
| Terraform | 1.8.x | IaC for cloud resources |
| KEDA | 2.14.x | Scale Temporal workers by queue depth |
| cert-manager + Traefik | latest / 3.x | TLS + ingress/gateway |
| GitHub Actions | — | CI: lint, test, isolation tests, build, deploy |
| Grafana + Prometheus + Loki | 10.x / 2.5x / 2.9x | Metrics/logs/alerts |
| Jaeger (dev) → OTel Collector | 1.5x | Trace backend Phase 1 (ClickHouse in M2) |
| MinIO | RELEASE-2024-x | S3-compatible storage (dev/self-host); AWS S3 in cloud |
| Resend / SES | — | Transactional email (approvals, invites) |
| LLMs | GPT-4o + GPT-4o-mini via LiteLLM | Generation vs cheap steps; Anthropic fallback configured |

---

## 7. Core Data Model

PostgreSQL 16, all tenant tables carry `tenant_id` with **Row-Level Security** enabled:

```
tenants            (id, name, plan, created_at)
users              (id, tenant_id, email, password_hash, oidc_sub, status)
workspace_members  (id, tenant_id, workspace_id, user_id, role)   -- admin|editor|viewer
workspaces         (id, tenant_id, name)
agents             (id, tenant_id, workspace_id, name, description, created_by)
agent_versions     (id, tenant_id, agent_id, version, dsl jsonb,
                    status draft|deployed|archived, created_at)    -- immutable once deployed
deployments        (id, tenant_id, agent_id, agent_version_id,
                    environment 'production', active bool)
connections        (id, tenant_id, name, kind http|slack|mock_hris,
                    credentials_encrypted bytea, created_by)       -- never plaintext
knowledge_bases    (id, tenant_id, workspace_id, name, embedding_model)
documents          (id, tenant_id, kb_id, filename, s3_key, status pending|ready|failed)
document_chunks    (id, tenant_id, document_id, chunk_index, content,
                    tokens, embedding vector(1536))                -- HNSW index
executions         (id, tenant_id, agent_version_id, trigger_type,
                    input jsonb, status running|waiting_approval|
                    success|failed|cancelled, started_at, finished_at,
                    total_cost_usd numeric(10,4), error text)
node_runs          (id, tenant_id, execution_id, node_id, node_type,
                    status, attempt, started_at, finished_at,
                    output_ref s3_key, cost_usd)
trace_spans        (id, tenant_id, execution_id, node_run_id,
                    span_kind llm_call|tool_call|retrieval|approval,
                    payload jsonb, tokens_in, tokens_out, cost_usd, duration_ms)
approval_tasks     (id, tenant_id, execution_id, node_run_id,
                    approver_role, assigned_user_id, channels jsonb,
                    timeout_at, escalated_to, decision
                    pending|approved|rejected|escalated|timeout,
                    decided_by, decided_at, comment)
audit_events       (id, tenant_id, actor_user_id, action, entity_type,
                    entity_id, metadata jsonb, created_at)         -- append-only, no UPDATE/DELETE grants
templates          (id, name, category, dsl jsonb, is_builtin)    -- global, seeded
```

**Indexes:** HNSW on `document_chunks.embedding`; composite `(tenant_id, …)` on every hot query; partial index on `executions(status)` for running/waiting.

---

## 8. API Surface

REST under `/api/v1` (JWT Bearer; `X-Tenant-Id` derived from token — never from client):

```
POST   /auth/register | /auth/login | /auth/oidc/callback
GET    /me

GET    /agents                      POST   /agents
GET    /agents/{id}                 PATCH  /agents/{id}
POST   /agents/{id}/generate        # NL → DSL draft (async job, streams progress)
POST   /agents/{id}/chat-edit       # conversational patch → new draft revision
GET    /agents/{id}/versions        POST   /agents/{id}/versions/{vid}/deploy
POST   /agents/{id}/rollback
GET    /agents/{id}/templates       POST   /agents/{id}/install-template/{tid}

GET    /executions?agent_id=        POST   /executions            # manual test run
GET    /executions/{id}             GET    /executions/{id}/trace
POST   /executions/{id}/cancel
POST   /webhooks/trigger/{agent_id} # signed external trigger (HMAC)

GET    /knowledge-bases             POST   /knowledge-bases
POST   /knowledge-bases/{id}/documents      # multipart upload → async ingest
GET    /knowledge-bases/{id}/query?q=

GET    /connections                 POST   /connections           # creds encrypted at rest
DELETE /connections/{id}

GET    /approvals?status=pending    POST   /approvals/{id}/approve|reject
WS     /ws/executions/{id}          # live node status stream (Redis pub/sub backed)

GET    /healthz /readyz /metrics
```

**Conventions:** Pydantic request/response models; RFC7807 problem+json errors; idempotency keys on POST executions; cursor pagination on lists.

---

## 9. Built-in Scalability Decisions

These are **non-negotiable in Phase 1** — they cost little now and prevent the "complete rewrite" the vision doc forbids:

| # | Decision | Cost now | Rewrite avoided later |
|---|---|---|---|
| S1 | **Durable runtime (Temporal), not in-process loops** | Small learning curve | Rebuilding execution state management for long/HITL runs |
| S2 | **Stateless core-api pods** (no local sessions, no local files) | Redis/S3 discipline | Session-sticky architecture that can't scale out |
| S3 | **RLS + tenant_id from day one** | One migration convention | Retro-fitting isolation across every query |
| S4 | **Immutable agent versions + deployment pointer** | Version table design | Retrofitting versioning onto mutable configs |
| S5 | **Trace emission inside the runtime contract** | Span writes per node | Post-hoc logging that can't answer trust questions |
| S6 | **Async job pattern for LLM generation & doc ingestion** (queue + poll/WS, never blocking request) | Job table + worker loop | Sync endpoints that time out at scale |
| S7 | **Vector store behind a repository interface** (pgvector impl first) | Thin abstraction | Migration pain when moving to Qdrant |
| S8 | **WebSocket hub on Redis pub/sub** (any pod can serve any client) | Pub/sub plumbing | Sticky-session WS architecture |
| S9 | **Secrets envelope-encrypted with per-tenant data keys** | KMS/Vault setup | Re-encrypting an existing credential store |
| S10 | **KEDA autoscaling on Temporal queue depth** | Helm chart config | Capacity incidents at first real load |
| S11 | **Audit events append-only from the first commit** | DB grant rules | Backfilling audit history |
| S12 | **DSL JSON Schema as the contract** between builder/runtime/UI | Schema authoring | Ad-hoc graph format drift |

**Scaling path after Phase 1 (same code):** replicas ↑ → pgbouncer + read replica → Qdrant swap-in → ClickHouse trace backend → Kafka for event fan-out → regional deployments. No architectural rework required at any step.

---

## 10. Environments & Deployment

| Environment | Purpose | Stack |
|---|---|---|
| `local` | Developer laptops | `docker compose up`: postgres+pgvector, redis, temporal, minio, litellm, core-api, worker, web |
| `staging` (cloud) | Integration + demo rehearsals | Managed K8s, managed Postgres/Redis, auto-deploy on merge to `main` |
| `production` (cloud) | Pilot customers | Same Helm charts, separate namespace/values; manual approval gate in CI |

**CI/CD pipeline (GitHub Actions):**
```
PR:   ruff+mypy → pytest (unit) → vitest → eslint → build images
main: integration tests (docker compose) → tenant-isolation test suite
      → push images → helm upgrade staging → smoke tests
prod: manual gate → helm upgrade --atomic → post-deploy smoke → auto-rollback on fail
```

**Observability baseline:** Prometheus metrics (API latency, queue depth, executions by status), Loki logs (structured JSON, no secrets/PII — redaction middleware), OTel traces to Jaeger, Grafana dashboard per service + alerts (error rate > 2%, queue depth > 100, DB connections > 80%).

**Repo layout (monorepo):**
```
EnterpriseAI/
├── apps/
│   ├── web/                    # Next.js
│   ├── core-api/               # FastAPI app
│   │   ├── modules/{iam,builder,registry,knowledge,tools,approvals,traces}/
│   │   └── main.py
│   └── runtime-worker/         # Temporal workers + node executors
├── packages/
│   ├── dsl-schema/             # JSON Schema + Pydantic models (shared FE/BE)
│   └── connectors/             # http, slack, mock_hris implementations
├── infra/
│   ├── docker-compose.yml      # full local stack
│   ├── helm/                   # charts per deployable
│   └── terraform/
├── templates/                  # builtin agent templates (DSL json)
└── .github/workflows/
```

---

## 11. Delivery Milestones

**4 × 2-week sprints. Each ends with a demoable increment on staging.**

### Sprint 1 — Foundation (Weeks 1–2)
- Monorepo scaffold, docker-compose full stack, CI pipeline green
- IAM module: register/login/OIDC, JWT, RBAC middleware, tenant+workspace bootstrap
- Postgres schema v1 + Alembic + **RLS policies**; tenant-isolation test suite (S3)
- DSL JSON Schema package (`packages/dsl-schema`) with validation + fixtures
- **Demo:** login → empty workspace; DSL validates via API

### Sprint 2 — Build Experience (Weeks 3–4)
- Registry: agents CRUD, draft revisions, version snapshots, deploy/rollback
- Builder module: NL→DSL generation via LiteLLM (async job), chat-edit patches, template install (3 templates seeded)
- Web: auth screens, agent list, **React Flow canvas** ⇄ DSL sync, node config forms
- **Demo:** "Create an employee onboarding agent" → graph appears; conversational edit adds approval step

### Sprint 3 — Run & Connect (Weeks 5–6)
- Runtime-worker: Temporal workflow interpreter for all 6 node types, retries, condition routing
- Tool Service: http/slack/mock_hris connectors, encrypted connections CRUD
- Knowledge Service: upload → Unstructured parse → chunk → embed → pgvector hybrid query
- Web: run panel, live canvas status (WS hub + Redis pub/sub)
- **Demo:** deploy agent → webhook/manual trigger → watch nodes light up live

### Sprint 4 — Trust & Release Hardening (Weeks 7–8)
- HITL approvals: approval tasks, email notification, in-app inbox, timeout escalation, audit events
- Trace viewer: span tree per execution incl. prompts/retrievals/cost
- Load test (k6): 200 concurrent executions; fix bottlenecks; KEDA verified
- Security pass: OWASP checks, secret-redaction tests, dependency scan, isolation re-test
- Pilot-ready staging + runbook; **golden-path release demo**

---

## 12. Acceptance Criteria (Golden Path Demo)

The release ships when this exact script passes on production-like staging:

1. New user registers → lands in workspace ✔
2. Types *"Create an employee onboarding agent"* → valid 7-node workflow renders on canvas < 30s ✔
3. Says *"Add a manager approval before creating the employee record"* → graph patch applied ✔
4. Drags a condition node visually and wires it to human-review path ✔
5. Uploads `hr_policies.pdf` → KB ready < 60s ✔
6. Configures `ai.agent` node to search that KB; connects mock HRIS + Slack credentials (stored encrypted) ✔
7. Runs a manual test → watches nodes transition live → sees retrieved policy chunks cited in trace ✔
8. Run pauses at Manager Approval → approver gets email → approves from inbox → run resumes ✔
9. Deploys version 1 → triggers via signed webhook → execution succeeds ✔
10. Opens trace: every LLM call, tool call, retrieval, approval decision visible with duration & cost ✔
11. Rolls back to a previous version; new executions use it immediately ✔
12. Automated suite proves Tenant A cannot read Tenant B's agents/knowledge/executions even with forged IDs ✔

**Exit gate metrics:** all P0 FRs pass · zero critical/high security findings · load test meets NFR table · runbook + rollback tested.

---

## 13. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| LLM generates invalid/unusable workflows | Core UX broken | Med | Strict JSON Schema + validator loop with one auto-repair retry; templates as guaranteed fallback |
| Temporal learning curve slows Sprint 3 | Schedule slip | Med | Spike in Sprint 1; keep workflow interpreter generic (one workflow class runs any DSL) |
| pgvector performance at scale | Slow retrieval | Low (Phase 1 volumes) | HNSW index + limits; S7 abstraction keeps Qdrant swap cheap |
| WebSocket complexity | Flaky live updates | Low–Med | socket.io reconnect/backoff; polling fallback endpoint |
| Credential leakage | Security incident | Low | Envelope encryption, redaction middleware, leak-detection tests in CI |
| Scope creep toward M2 features | Missed release | High | Out-of-scope list is contractual; changes go through release-plan amendment |
| LLM cost overrun during development | Budget | Med | LiteLLM budget caps; GPT-4o-mini for dev/test; caching for repeated generations |

---

## Appendix A — Definition of Done (per feature)

- [ ] Unit tests ≥ 80% on backend modules; integration test for API flows
- [ ] Tenant-isolation test added for any new tenant-scoped entity
- [ ] OpenAPI schema updated; frontend types generated
- [ ] Traces emitted for every new runtime path
- [ ] Audit event written for state-changing actions
- [ ] Feature demoed on staging; runbook updated if operational

## Appendix B — Team Shape (suggested)

| Role | Count | Focus |
|---|---|---|
| Backend/AI Engineer | 2 | core-api modules, builder prompts, knowledge service |
| Platform/Runtime Engineer | 1 | Temporal runtime, infra, Helm/K8s, CI/CD |
| Frontend Engineer | 1–2 | Canvas, forms, live status, trace viewer |
| Product/Design | 0.5 | Golden-path UX, demo script |
| QA (shared) | 0.5 | Isolation tests, load tests, acceptance script |





