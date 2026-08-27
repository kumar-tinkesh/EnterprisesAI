# Enterprise AI Agent Platform
## Product, Architecture & Execution Plan
**Source:** `PRODUCT_VISION_AGENTS.pdf` (Product North Star)
**Prepared from the perspectives of:** Product Management, Business Analysis, Solution Architecture, QA

---

## Notation Used Throughout

Every material claim in this document is tagged so you can separate the vision from my analysis:

| Tag | Meaning |
|---|---|
| **[STATED]** | Explicitly written in the vision document |
| **[IMPLIED]** | Not written, but logically unavoidable given what is stated |
| **[ASSUMPTION]** | My assumption, needs business confirmation before it is treated as fact |
| **[RECOMMENDED]** | My professional recommendation, not from the document |
| **[GAP]** | Missing, ambiguous, or contradictory in the source, needs a decision |

---

# 1. Project Understanding

## 1.1 The Core Problem

**[STATED]** Enterprises want AI for business operations (Finance, HR, Sales, Support, IT, Legal, Operations), but building one agent requires stacking LLM expertise, backend engineering, API integrations, RAG, workflow orchestration, security, authentication, monitoring, evaluation and deployment. This makes AI automation expensive and slow.

**Sharper restatement of the problem [ANALYSIS]:**
The problem is not that AI is difficult. The problem is that **the fixed assembly cost of a production AI workflow exceeds the value of any single automation.** Every department rebuilds the same ten layers to automate one process. The economic insight behind this product is amortization: build the ten layers once, sell the eleventh layer (the business logic) many times.

This reframing matters because it dictates the product strategy: **the moat is not the agent builder, it is the operating layer** (governance, trace, approval, isolation, versioning). A competitor can clone a canvas in a quarter. Re-creating audited, multi-tenant, durable agent execution takes far longer.

## 1.2 Target Users

**[STATED]** Document audience is Engineering and AI/ML. Departmental demand is named: Finance, HR, Sales, Customer Support, IT, Legal, Operations.

**[STATED]** Section 30 defines success as a customer doing the full lifecycle *"without engineering assistance"*, which establishes the primary user as a **non-engineer business person**.

**[GAP] The document never separates buyer from user.** This is the single most consequential unresolved question in the vision. Three very different products follow from three different answers:

| If the primary user is... | The product becomes... | Consequence |
|---|---|---|
| A business analyst in Finance/HR | A citizen-automation SaaS | Templates and NL creation dominate, integration must be zero-code, sales is bottom-up |
| A central AI Center of Excellence team | An internal platform product | SDK, code escape hatches and governance dominate, sales is top-down |
| An enterprise developer | A LangGraph competitor | Canvas is secondary, APIs are primary, marketplace is unlikely to work |

Section 3 says the user should not need to understand MCP, vector databases or tool calling. Section 26 says the first release lets a customer configure "Models, Tools, MCP, Knowledge, Memory, Output, Guardrails". **These two statements contradict each other** and must be reconciled before UX design starts. My reading is that the intended answer is a two-persona product (business author plus technical steward), which is workable but must be designed for deliberately rather than by accident.

## 1.3 Main Product

**[STATED]** An enterprise agent operating platform, explicitly not a chatbot, not a workflow builder, not a prompt manager, not an LLM API wrapper, not a code generator. Five layers: **Create (Agent Builder), Operate (Agent Runtime), Discover (Marketplace)**, over a core of **Models, Tools, RAG, Memory, Governance**.

## 1.4 Primary Value Proposition

**[STATED]** Go from "I have a business problem" to "I have a production-ready AI agent solving this problem" without building each AI workflow from scratch.

**[ANALYSIS]** The value proposition has two halves that appeal to two different buyers, and both must be present for a sale to close:
- **Speed of creation** (appeals to the business unit): describe it, see it, deploy it.
- **Trust in operation** (appeals to IT, Security, Risk, Compliance): every execution is traced, permissioned, approvable and auditable.

Section 16 states "Trust Is a Core Product Feature." **[ANALYSIS]** I would go further: trust is the *deal-closing* feature, and speed is the *deal-opening* feature. Demos win on speed. Procurement is won on trust. Both must be in the MVP, which is why I do not recommend deferring traces or tenant isolation to Phase 2.

## 1.5 Key Business Goals

**[IMPLIED]** from Sections 20, 21, 18:
1. Sell a commercial multi-tenant SaaS to enterprises.
2. Reach production quality (HA, security, scalability, observability, reliability, auditability, versioning, governance) without a rewrite.
3. Build a marketplace ecosystem for long-term defensibility and land-and-expand revenue.
4. Reduce time-to-first-agent so radically that the platform becomes the default place enterprise automation begins.

**[GAP]** No revenue model, pricing metric, target customer size, target market or success metric is stated. Section 9 shows a per-execution cost of $0.09, which implies metering exists, but not how it is monetized.

## 1.6 Assumptions Embedded in the Vision

These are assumptions the *document* makes. Each is a risk if false.

| # | Assumption in the vision | Status | Risk if wrong |
|---|---|---|---|
| A1 | An LLM can reliably turn a one-line business description into a correct, executable agent graph | **Unvalidated, highest risk** | The headline experience becomes a demo trick, users abandon after the first bad generation |
| A2 | Business users want to see and edit a workflow graph | Plausible but unproven | Canvas becomes intimidating, product reverts to a chat UI |
| A3 | Enterprises will connect production CRM/ERP/HRIS/accounting systems to a third-party AI platform | Optimistic | Blocked at security review, forces on-prem or VPC deployment, huge architecture impact |
| A4 | Integration can be generic enough to avoid per-agent custom code | Partly true | The integration long tail becomes an unbounded services business |
| A5 | Marketplace agents are portable across tenants | Questionable | Each tenant's ERP schema, approval chain and policies differ, so "install and run" may become "install and rebuild" |
| A6 | One prototype architecture can scale to production without a rewrite | Achievable but only with specific early decisions (see Section 11) | Rewrite, exactly what Section 21 forbids |
| A7 | Deterministic workflow orchestration and autonomous agent reasoning can coexist in one model | True, but the boundary must be explicit | Users cannot predict behavior, trust collapses |

---

# 2. Features & Functionality

Every feature below is derived from the document. The **Source** column shows the vision section. Priority uses Must / Should / Nice, scoped against the stated goal of a sellable first release.

## 2.1 Create (Agent Builder)

| Feature | Purpose | Primary User | Expected Behavior | Dependencies | Priority | Phase | Source |
|---|---|---|---|---|---|---|---|
| **NL Agent Generation** | Turn a business description into a draft agent | Business Author | User types intent, system returns a named agent with an ordered node graph, each node typed (trigger, agent, knowledge, condition, tool, approval, notification) and pre-wired | Agent Spec schema, tool catalog, LLM designer prompt | Must | MVP | S5A, S12 |
| **Visual Agent Canvas** | Inspect and manually build agents | Business Author, Technical Steward | Drag, connect, insert, delete, reorder nodes, node config panel, validation errors shown inline | Agent Spec schema, graph editor | Must | MVP | S5B |
| **Conversational Editing** | Modify an existing agent by chat | Business Author | "Add a manager approval before creating the record" produces a **visible diff** the user accepts or rejects, not a silent regeneration | NL generation, graph patch engine | Must | MVP | S14 |
| **Templates** | Fast start from a known pattern | Business Author | Gallery of Finance / HR / Sales / Support / IT agents, cloned into the tenant then customized | Agent Spec, seed content | Must | MVP | S5C |
| **Node Library** | The vocabulary of the builder | All builders | Trigger, AI Agent, Knowledge, Condition, Tool, Human Approval, Notification at minimum | Runtime executors per node type | Must | MVP | S5B |
| **Graph Validation** | Prevent broken agents reaching production | Builder | Pre-deploy check for unreachable nodes, cycles, unbound tools, missing credentials, unmapped outputs | Spec schema | Must | MVP | S14 |
| **Agent Metadata** | Findability and ownership | Builder, Admin | Name, description, owner, department, tags, criticality | Data model | Should | MVP | Implied |

**[RECOMMENDED] Critical design decision on conversational editing:** the LLM must emit a **patch** (a list of graph mutations such as `insert_node_before`, `set_edge`, `update_config`), never a whole regenerated graph. Reasons: the user can review a diff, edits are reversible, manual and AI edits can be interleaved without clobbering, and every change becomes an auditable event. Full-regeneration will silently destroy user configuration and will be the single largest source of trust loss in this product.

## 2.2 Agent Intelligence

| Feature | Purpose | User | Behavior | Dependencies | Priority | Phase | Source |
|---|---|---|---|---|---|---|---|
| **Intent understanding & reasoning** | Agent decides how to handle a task | End Consumer | Model reasons over inputs within the node's scope | Model layer | Must | MVP | S6 |
| **Tool selection & calling** | Agent picks and invokes tools | Runtime | Constrained to tools explicitly bound to the agent, never the global catalog | Tool registry, policy engine | Must | MVP | S6, S17 |
| **Knowledge retrieval** | Ground answers in company data | Runtime | Retrieve top-k chunks from bound knowledge bases, retrieved context recorded in the trace | RAG pipeline | Must | MVP | S6, S8 |
| **Structured output** | Downstream nodes need typed data | Runtime | Node declares an output schema, runtime validates and repairs | Schema validation | Must | MVP | S6 |
| **Ask humans for help** | Escalation when uncertain | Runtime, Approver | Agent can raise a human task mid-run | Approval system, durable execution | Must | MVP | S6, S15 |
| **Failure handling** | Reliability | Runtime | Retry with backoff, fallback path, dead-letter, compensating action | Durable execution | Must | MVP | S6 |
| **Long-running tasks** | Real business processes take days | Runtime | Execution suspends and resumes without holding a process | Durable execution engine | Must | MVP | S6 |
| **Memory** | Recall relevant information | Runtime | **[GAP]** never defined in the vision | Memory store | Should | Phase 2 | S6, S4 |
| **Multi-agent (manager plus specialists)** | Complex cross-department work | Builder | A manager agent delegates to sub-agents | Everything above, plus agent-as-tool | Nice | Phase 3 | S6 (explicitly "eventually") |

**[GAP] Memory is listed as one of five core platform primitives in the Section 4 architecture diagram, and is listed in the first release scope in Section 26, but is never defined anywhere in the document.** At least four different things are called "memory" in this product category: per-conversation history, per-execution scratchpad, cross-execution entity memory (for example "this vendor is always late"), and semantic memory that overlaps with RAG. These have different data models, different retention rules and very different privacy implications under GDPR. This needs a product decision before it can be estimated.

## 2.3 Connect (Tools & Integrations)

| Feature | Purpose | User | Behavior | Dependencies | Priority | Phase | Source |
|---|---|---|---|---|---|---|---|
| **Connector catalog** | Browse available systems | Admin, Builder | List of supported systems with auth status | Connector framework | Must | MVP | S7 |
| **OAuth connection flow** | Authorize a system once, reuse everywhere | Workspace Admin | Standard OAuth 2.0 authorization code flow, tokens stored encrypted, refresh handled by platform | Secret vault | Must | MVP | S7 (implied) |
| **Tool binding to an agent** | Grant a specific agent specific capabilities | Builder | Select connection, then select the exact allowed actions | Policy engine | Must | MVP | S17 |
| **Action-level permissions** | "Can read invoices, cannot delete invoice" | Admin | Enforced at runtime by the policy decision point, not just hidden in UI | Policy engine | Must | MVP | S17 |
| **MCP server connection** | Use any MCP-exposed tool | Technical Steward | Register an MCP server, discover its tools, bind selected tools to agents | MCP client layer | Must | MVP | S7, S26 |
| **Generic HTTP / Internal API connector** | Cover the long tail | Technical Steward | Define base URL, auth, endpoints, request/response schema | Connector framework | Must | MVP | S7 ("Internal APIs") |
| **Named connectors** (CRM, ERP, HRIS, Accounting, Databases, Email, Slack, Teams, WhatsApp, Ticketing) | Out-of-box value | Admin | Prebuilt, tested, schema-mapped | Per-connector work | Should | Phased | S7 |

**[ANALYSIS] The integration long tail is the most underestimated cost in this vision.** Section 7 names eleven categories, which in practice means dozens of vendors and hundreds of API surfaces. Section 7 also promises the customer will not write custom integration code "for every agent". The realistic strategy is a three-tier one, described in Section 9 of this document.

## 2.4 Knowledge

| Feature | Purpose | User | Behavior | Dependencies | Priority | Phase | Source |
|---|---|---|---|---|---|---|---|
| **Knowledge base as reusable object** | One KB, many agents | Admin, Builder | Create KB, upload documents, bind to N agents | Vector store | Must | MVP | S8 |
| **Ingestion pipeline** | Documents to retrievable chunks | System | Upload, parse, chunk, embed, index, with visible per-document status | Storage, embedding model, job queue | Must | MVP | S8 |
| **Retrieval** | Ground the agent | Runtime | Top-k retrieval with the retrieved chunks recorded in the trace | Vector store | Must | MVP | S8, S16 |
| **Source citation** | Trust and verification | End Consumer | Answers cite the source document and section | Retrieval metadata | Should | MVP | Implied by S16 |
| **KB-level access control** | Not all users see all knowledge | Admin | Permissions at knowledge level | RBAC | Must | MVP | S17 |
| **Live connector-sourced knowledge** (SharePoint, Drive, Confluence sync) | Knowledge stays current | Admin | Scheduled re-sync and re-index | Connectors, scheduler | Should | Phase 2 | Implied |
| **Retrieval testing / playground** | Debug bad answers | Builder | Run a query, see what would be retrieved and with what score | Retrieval API | Should | Phase 2 | Implied by S9 "Debug" |

## 2.5 Human-in-the-Loop

**[STATED]** Section 15 requires: Approver, Role, Timeout, Escalation, Approval conditions, Rejection path, Audit trail. This is unusually specific for a vision document, which signals it is a known enterprise requirement. All seven are Must / MVP.

| Feature | Behavior | Priority | Phase |
|---|---|---|---|
| Approval node with named approver or role | Route to a person or any member of a role | Must | MVP |
| Conditional approval | Approval required only when a condition is met (for example risk score above threshold) | Must | MVP |
| Timeout and escalation | On expiry, escalate to a defined fallback, or take a default action defined by the builder | Must | MVP |
| Rejection path | Explicit branch for rejection, with a required reason | Must | MVP |
| Approval audit record | Who, when, what they saw, what they decided, immutable | Must | MVP |
| Out-of-app approval (email / Slack / Teams action) | Approve without logging into the platform | Should | MVP |
| Delegation and out-of-office | Reassign approvals when an approver is unavailable | Should | Phase 2 |
| Segregation of duties (no self-approval) | Requester cannot approve their own request | Should | Phase 2 |

**[ANALYSIS]** The approval feature is what forces **durable execution** into the MVP. An agent that pauses for three days waiting for a manager cannot be a synchronous HTTP request or a short-lived function. This single requirement determines the backend architecture, and getting it wrong is exactly the kind of rewrite Section 21 warns against.

## 2.6 Test & Evaluate

| Feature | Purpose | User | Behavior | Priority | Phase | Source |
|---|---|---|---|---|---|---|---|
| **Manual test run** | Try the agent with sample input | Builder | Run in a sandbox with a visible live trace | Must | MVP | S26 |
| **Live execution visualization** | Watch the agent work on the canvas | Builder | Node states stream: pending, running, completed, failed, waiting on human | Must | MVP | S13 |
| **Dry-run / simulation mode** | Test without real side effects | Builder | Tool writes are mocked or sent to sandbox credentials | **[RECOMMENDED] Must** | MVP | Not in document |
| **Test datasets** | Repeatable multi-case testing | Builder | A set of inputs plus expected outcomes, run as a batch | Must | Phase 2 | S26 |
| **Evaluation framework** | Decide if an agent is good enough | Builder, Approver | Scored runs against criteria, pass/fail gate before deploy | Must | Phase 2 | S9, S10, S24 |
| **Regression comparison between versions** | Did v3 break what v2 did well | Builder | Side-by-side eval results per version | Should | Phase 2 | Implied by S10 |

**[GAP] "Evaluate" appears in the lifecycle (S10), the north-star journey (S24) and the definition of success (S30), but the document never defines what evaluation means, who defines pass criteria, or whether a failed evaluation blocks deployment.** This is a substantial product design area, not a checkbox, and it is one of the hardest parts of the whole platform.

**[RECOMMENDED] Dry-run mode is missing from the vision and belongs in the MVP.** The prototype scenario in Section 25 includes "Create Employee Record", a write action against a real HRIS. Without a simulation mode, every test run creates a real employee. No enterprise will test on production systems, and requiring separate sandbox credentials for every connector before a user can test once will kill activation.

## 2.7 Deploy & Operate

| Feature | Purpose | User | Behavior | Priority | Phase | Source |
|---|---|---|---|---|---|---|---|
| **Versioning** | Immutable, referenceable agent versions | Builder | Every deploy pins a version, versions are diffable | Must | MVP | S9, S26 |
| **Environments (staging, production)** | Safe promotion | Builder, Admin | A version is deployed to an environment, environments have separate credentials | Must | MVP (may start with 2 fixed envs) | S26 |
| **Deploy / Rollback** | Ship and un-ship safely | Builder, Admin | One-click deploy of a version, rollback to a previous version | Must | MVP | S26 |
| **Triggers** | How agents start | Builder | Manual, scheduled, webhook, event-from-connector, API call | Must (manual plus schedule in MVP) | Phased | S5B, S25 |
| **Execution trace** | Full record of one run | Builder, Auditor, Admin | Every item listed in Section 16 captured per execution | Must | MVP | S16 |
| **Monitoring dashboard** | Health of the agent fleet | Operator, Admin | Success rate, latency, cost, volume, error breakdown | Must | MVP | S9, S26 |
| **Cost tracking** | Per execution, per agent, per tenant | Admin | Token and tool cost attributed and aggregated | Must | MVP | S9 ("Cost: $0.09") |
| **Alerting** | Know before the customer does | Operator | Threshold alerts on failure rate, latency, cost, queue depth | Should | Phase 2 | Implied by S9 "Monitor" |
| **Debugging tools** | Diagnose a failed run | Builder | Inspect any step's exact input and output, re-run from a step | Should | Phase 2 | S9 ("Debug") |
| **Improve loop** | Turn production data into a better agent | Builder | Suggestions derived from failure patterns | Nice | Phase 3 | S10 ("Improve") |

## 2.8 Governance

**[STATED]** Section 17 requires permissions at every level: User, Workspace, Agent, Knowledge, Tool, Action. Section 20 requires strict tenant isolation across Agents, Knowledge, Credentials, Executions, Users, Logs and Business data.

| Feature | Priority | Phase |
|---|---|---|
| RBAC with system roles | Must | MVP |
| Tenant isolation enforced at the data layer | Must | MVP |
| Agent-level permission grants (which tools, which actions) | Must | MVP |
| Immutable audit log of every privileged action | Must | MVP |
| Approval-required actions (for example payment) | Must | MVP |
| Guardrails (PII redaction, blocked topics, output constraints) | Should | Phase 2 |
| Custom roles | Should | Phase 2 |
| SSO (SAML / OIDC) and SCIM provisioning | **[GAP] not mentioned but mandatory for enterprise sales** | Phase 2 |
| Data residency selection | **[GAP] not mentioned, likely mandatory for EU customers** | Phase 3 |

## 2.9 Marketplace

**[STATED]** Section 18 and 19: discover, install, configure, test, deploy. A marketplace agent bundles Agent + Workflow + Tools + Knowledge + Guardrails + Evaluation + Configuration, so customers are installing "a business capability".

| Feature | Priority | Phase |
|---|---|---|
| Browse and search listings | Should | Phase 3 |
| Install into a tenant (copy-on-install, then locally editable) | Should | Phase 3 |
| Post-install configuration wizard (map tools, credentials, approvers, knowledge) | Should | Phase 3 |
| Versioning and updates of installed agents | Should | Phase 3 |
| Third-party publishing, review and certification | Nice | Phase 3+ |
| Ratings, usage stats, monetization | Nice | Phase 3+ |

**[GAP] Marketplace publishing model is undefined.** First-party only, or third-party ISVs? Free or paid? Who certifies security? Who is liable when an installed agent takes a wrong action against a customer's ERP? These are legal and commercial decisions, not engineering ones, and they change the architecture (third-party code needs sandboxing and a review pipeline).

**[ANALYSIS] The marketplace has an unaddressed portability problem.** A marketplace "Invoice Collection Agent" must bind to a specific accounting system, a specific field schema, a specific approval chain and specific company policy. The reusable part is the *pattern*, not the *configuration*. I recommend designing marketplace agents as **parameterized blueprints with a declared configuration contract** (required tool capabilities, required knowledge types, required roles), so install becomes a guided mapping exercise rather than a promise that breaks on first run.

---

# 3. User Roles

**[GAP]** The vision names no roles at all. It requires RBAC (S26) and permissions at six levels (S17) but never enumerates who exists. Everything below is **[RECOMMENDED]**, derived from the capabilities the document requires.

## 3.1 Role Matrix

| Role | Can Do | Cannot Do | Data Access | Key Permissions |
|---|---|---|---|---|
| **Platform Super Admin** (vendor side) | Manage tenants, provision, view platform-wide health, impersonate with consent and audit | Read tenant business data without an audited break-glass flow | Metadata across tenants, never payload data by default | `platform:*` |
| **Tenant Owner / Org Admin** | Billing, SSO config, workspaces, invite users, assign roles, set org policies, view audit log | Bypass approval requirements they configured | Everything in their tenant | `tenant:admin` |
| **Workspace Admin** | Manage a workspace's members, connections, knowledge bases, deployment approvals | Change billing or org-level policy | Everything in their workspace | `workspace:admin` |
| **Agent Builder / Author** | Create, edit, test agents, bind tools already connected, bind knowledge already available, deploy to staging | Create connections with new credentials, deploy to production (if gated), see raw secrets | Agents and executions in their workspace | `agent:write`, `deploy:staging` |
| **Approver / Business Reviewer** | Approve or reject runtime human tasks, and optionally approve production deployment | Edit agents | The specific approval context plus the trace of that execution | `approval:act` |
| **Agent Operator / SRE** | Monitor fleet, pause or disable a running agent, retry failed executions, manage alerts | Change agent logic | Executions, traces, metrics | `runtime:operate` |
| **Auditor / Compliance** | Read-only access to all traces, audit logs, permission grants, export evidence | Change anything | Read-all within tenant, including redacted payloads per policy | `audit:read` |
| **Technical Steward / Integration Engineer** | Register MCP servers, define custom HTTP connectors, configure OAuth apps, manage secrets | Necessarily nothing about business logic, though usually also a Builder | Connection configs, no plaintext secrets after save | `connection:write` |
| **End Consumer** | Trigger an agent, chat with it, supply inputs, view their own results | See agent internals, other users' executions, or the tool credentials | Only their own executions | `agent:invoke` |
| **Marketplace Publisher** (Phase 3) | Publish, version and support listings | Access installing tenants' data | Their own listings plus anonymized install metrics | `marketplace:publish` |

## 3.2 Role Design Notes

- **[RECOMMENDED] Separate "can build" from "can connect".** Credential creation is a security-sensitive act. Letting any business author paste a production ERP API key into the platform is how this product fails a security review.
- **[RECOMMENDED] Separate "can deploy to production" from "can build".** This is the enterprise change-management expectation and it maps directly to Section 10's Approve-then-Deploy step.
- **[RECOMMENDED] Runtime identity is distinct from user identity.** When an agent calls QuickBooks, whose credential is used? The three options (service account owned by the workspace, the builder's delegated token, or the invoking end user's token) have very different security and audit properties. **[GAP]** The vision does not address this and it must be decided in week one, because it changes the credential model, the audit model and the connector design. My recommendation: workspace-owned service connections by default, with optional per-user delegated auth for agents that act on behalf of an individual.
- **[GAP]** The vision requires permissions at Workspace level (S17) but never explains what a workspace is or whether it maps to a department, a team, a project or an environment. I assume **department or team** and recommend confirming.

---

# 4. User Journeys

## 4.1 Journey A: Business Author creates the first agent (the golden path)

This is the journey Section 24 and Section 30 define as the product.

```
Invite received / SSO login
        ↓
Onboarding: pick department, pick a starting point
        ↓
Empty state: "Describe the process you want to automate"
        ↓
User types: "Create an employee onboarding agent"
        ↓
[AI DESIGNS] streaming: agent name, purpose, node-by-node graph appears
        ↓
Canvas renders the workflow + a plain-language explanation of each step
        ↓
User reviews. Two edit paths, interchangeable:
   (a) Chat: "Add a manager approval before creating the employee record"
       → system shows a DIFF → user accepts
   (b) Canvas: click node, edit config, drag a new node in
        ↓
Unresolved requirements surface as inline TODO badges on nodes:
   • "Connect an HRIS" (tool not connected)
   • "Choose a knowledge base" (no HR policies uploaded)
   • "Select an approver" (approval node incomplete)
        ↓
User clicks a TODO → guided setup, or "Request access" if they lack permission
        ↓
Test: user enters sample employee data → DRY RUN
        ↓
Live canvas: nodes light up sequentially, approval node pauses
        ↓
User approves in-app (acting as the approver in test mode)
        ↓
Run completes: trace shown (steps, model, retrieved docs, tools called, cost, duration)
        ↓
User clicks Deploy → validation gate (schema ✓, credentials ✓, permissions ✓, tests ✓)
        ↓
If production deploy requires approval → request sent to Workspace Admin
        ↓
Version v1 deployed to Production
        ↓
Agent detail page: live monitoring, execution list, "Improve" entry point
```

**Critical UX requirements this journey imposes [ANALYSIS]:**
1. **The first generation must never be a dead end.** If the AI cannot map a step to a real tool, it must still produce the node, marked as unconfigured, with a clear next action. A generation that returns "I could not do that" destroys the core promise.
2. **The gap between "generated" and "runnable" must be visible and small.** The vision's biggest UX risk is that generation feels magical and then the user hits twelve configuration blockers. The TODO-badge pattern turns that cliff into a checklist.
3. **Test must be possible before any real integration exists** (mock tool responses), otherwise time-to-first-successful-run is measured in days, not minutes.

## 4.2 Alternative and failure paths for Journey A

| Path | Trigger | Expected behavior |
|---|---|---|
| Ambiguous request | "Create an agent for finance" | AI asks 1 to 3 clarifying questions, then generates. Never more than 3, or it stops feeling like magic |
| Wrong generation | Generated graph does not match intent | "Regenerate" with feedback, and full undo history. Prior versions never lost |
| No tool available | Agent needs Workday, not connected | Node created as unconfigured, user offered generic HTTP connector or "Request from admin" |
| User lacks permission | Author cannot create connections | In-product request flow to the Workspace Admin, agent saved as draft |
| Test fails | Tool returns 401 | Error surfaced at the specific node with the actual upstream message, plus a "Reconnect" action |
| Deploy blocked | Validation fails | Blocking list with a jump-to-node link per issue |
| Non-deterministic test | Passes once, fails once | Prompt user to run a test set rather than trusting a single pass (a real trust moment) |

## 4.3 Journey B: Approver responds to a runtime human task

```
Agent execution reaches Human Approval node
        ↓
Execution SUSPENDS durably (no compute held)
        ↓
Notification: email / Slack / Teams / in-app, per configuration
        ↓
Approver opens the approval view (deep link, may be outside the platform)
        ↓
Sees: what the agent proposes to do, why (agent reasoning),
      the source data, retrieved knowledge, and the exact
      consequence of approving ("This will create an employee record in Workday")
        ↓
Approve / Reject (+ mandatory reason on reject) / Request changes
        ↓
Decision recorded immutably (who, when, what version, what payload hash)
        ↓
Execution RESUMES on the approved or rejected branch
        ↓
Requester notified of the outcome
```

**Alternative paths:** timeout expires → escalate to a configured fallback approver → escalate again → final timeout action (fail, or take the builder's declared default). Approver has left the organization → reassignment rule. Approver clicks a stale link after a decision was already made → clear "already decided by X at Y" state, never a double-execute.

**[ANALYSIS] The single most important detail in this journey:** the approver must see the **consequence**, not the raw payload. "Approve JSON blob" is a compliance theatre pattern that enterprises specifically distrust. This is where trust is won or lost, and it deserves dedicated design work.

## 4.4 Journey C: Workspace Admin connects an enterprise system

```
Admin → Connections → Add connection → choose system
        ↓
OAuth consent screen (or API key / service account form for non-OAuth systems)
        ↓
Platform stores credential encrypted, never displays it again
        ↓
Connection test call runs immediately, result shown
        ↓
Admin scopes the connection: which actions are permitted at all
   (e.g. invoices: read ✓, create ✓, delete ✗)
        ↓
Admin decides which workspaces / agents may use this connection
        ↓
Connection appears in Builders' tool picker, constrained to allowed actions
```

**Alternative paths:** token expiry, revoked consent, IP allowlisting required by the customer's system, connector requiring an on-prem gateway to reach a system behind a firewall (**[GAP]** the vision never addresses on-prem reachability, yet ERP and databases are frequently not internet-facing; this is a common enterprise blocker and probably needs an agent/gateway component).

## 4.5 Journey D: Operator investigates a production failure

```
Alert: "Invoice Agent failure rate 18% in the last hour"
        ↓
Fleet dashboard → agent detail → filtered execution list (failed)
        ↓
Open one execution trace → failing step highlighted
        ↓
Inspect exact input, output, model, prompt, retrieved chunks, tool response, error
        ↓
Diagnose: upstream API schema changed
        ↓
Actions available: pause agent / roll back to previous version /
                   fix and redeploy / bulk retry the failed executions
        ↓
Post-fix: bulk replay of failed executions from the point of failure
```

**[RECOMMENDED]** Bulk replay from a failure point is not in the vision but is what makes an operator's life tolerable. It requires that execution state be checkpointed per step, which is another reason durable execution belongs in the foundation.

## 4.6 Journey E: End Consumer uses a deployed agent

```
Employee opens the agent (portal link / Slack / Teams / embedded)
        ↓
Submits a request or the agent is event-triggered
        ↓
Progress shown in business language ("Checking your leave balance...")
        ↓
Agent may ask a clarifying question
        ↓
Result delivered, with citations where knowledge was used
        ↓
Feedback control (thumbs up/down + comment) → feeds the Improve loop
```

**[GAP] The vision never describes the end-consumer surface.** Section 7 lists Slack, Teams and WhatsApp as connectable systems, which implies agents are consumed in chat, but Section 5's builder is a web app. Is there an end-user portal? An embeddable widget? Chat-only? This is a significant scope question, because "how does a normal employee actually use a deployed agent" is unanswered, and for several of the named use cases (HR support, IT helpdesk) it is the whole product.

## 4.7 Journey F: Install from Marketplace (Phase 3)

```
Discover (browse by department / search by problem)
        ↓
Listing detail: what it does, what it needs, what it costs, sample trace
        ↓
Install → creates a tenant-local editable copy (never a live reference)
        ↓
Configuration wizard: map required tool capabilities to existing connections,
     map roles to real approvers, attach or create the required knowledge bases
        ↓
Run the bundled evaluation suite against the tenant's actual configuration
        ↓
Review results → Test → Deploy
```

---

# 5. Admin Functionality

The vision requires governance (S17), tenant isolation (S20), audit (S26) and operations (S9) but never specifies an admin surface. The following is the derived requirement set. Note there are **two distinct admin products**, which the vision conflates.

## 5.1 Customer Admin (tenant-facing)

| Area | Capabilities | Priority | Phase |
|---|---|---|---|
| **Org dashboard** | Agent count, executions, success rate, spend vs budget, pending approvals, incidents | Must | MVP |
| **User management** | Invite, deactivate, assign roles, view last activity, bulk actions | Must | MVP |
| **Roles & permissions** | Assign system roles, grant agent/knowledge/tool/action scopes, define custom roles later | Must | MVP (system roles) |
| **Workspace management** | Create workspaces, assign members, set per-workspace policy | Should | MVP (basic) |
| **Connections** | Create, test, rotate, revoke connections, see which agents depend on each | Must | MVP |
| **Knowledge management** | Create KBs, review documents, re-index, set access, see storage usage | Must | MVP |
| **Agent registry** | Every agent in the tenant, owner, status, version, environment, last run, risk level | Must | MVP |
| **Deployment governance** | Require approval for production deploys, freeze windows, who deployed what when | Should | MVP |
| **Policy configuration** | Which tool actions always require human approval, spend limits, allowed models, data-retention period | Must | Phase 2 (a minimal always-approve list in MVP) |
| **Audit log** | Immutable, searchable, filterable, exportable (CSV/JSON, and SIEM streaming later) | Must | MVP |
| **Cost & usage** | Spend by agent, workspace, user, model, connector, with budgets and alerts | Must | MVP (view), Phase 2 (budgets) |
| **Notification settings** | Channels, routing rules, digest frequency, escalation defaults | Should | Phase 2 |
| **Error management** | Failed execution queue, categorized by cause, bulk retry, dead-letter inspection | Should | Phase 2 |
| **Security settings** | SSO/SAML, SCIM, session policy, IP allowlist, API key management | Must for enterprise sales | Phase 2 |
| **Data controls** | Retention periods, PII redaction rules, export, right-to-erasure handling | Must for GDPR | Phase 2 |

## 5.2 Vendor / Platform Admin (internal, back-office)

**[RECOMMENDED]** This is entirely absent from the vision but is required to operate a multi-tenant SaaS. Building it late is a common and painful mistake.

| Area | Capabilities |
|---|---|
| Tenant lifecycle | Provision, suspend, delete, set plan and quotas |
| Fleet health | Cross-tenant execution volume, error rates, queue depth, provider health |
| Model provider ops | Key rotation, provider failover, rate-limit budget allocation across tenants |
| Support tooling | Audited, consent-gated impersonation, with the tenant notified |
| Feature flags | Per-tenant rollout of new node types and models |
| Billing operations | Usage export, invoice reconciliation, overage handling |
| Abuse & safety | Detect prompt-injection incidents, runaway spend, malicious MCP registrations |
| Marketplace review | Listing submission queue, security scan, certification (Phase 3) |

---

# 6. Client / Customer Functionality

Consolidated view of what a customer organization can do end to end. All items derive from Sections 5 through 26.

**Create:** describe an agent in natural language, generate a draft, edit conversationally, edit visually, start from a template, clone an existing agent, import from marketplace (Phase 3).

**Configure:** choose model, set instructions and guardrails, bind tools with action-level scope, bind knowledge bases, define output schema, define triggers, define approval nodes with approvers, timeouts, escalation and conditions, set retry and failure policy, set cost and time limits.

**Connect:** authorize enterprise systems, register MCP servers, define custom HTTP connectors, manage credentials and rotation, scope actions per connection.

**Know:** create knowledge bases, upload and sync documents, monitor ingestion, test retrieval, share knowledge across agents, control who can query which knowledge.

**Test:** run manually with sample input, dry-run without side effects, run a test dataset, inspect the live canvas, inspect a full trace, compare versions.

**Evaluate:** define pass criteria, run evaluations, gate deployment on results (Phase 2).

**Deploy:** version, promote through staging to production, roll back, pause, schedule, disable.

**Operate:** monitor success rate, latency, cost and volume, drill into any execution, retry failures, receive alerts, export reports.

**Govern:** manage users and roles, enforce action-level permissions, review approvals, read audit logs, enforce spend limits, prove to an auditor exactly what an agent did and who authorized it.

**Consume:** trigger agents, chat with them, respond to their questions, approve their proposed actions, give feedback on results.

---

# 7. AI Opportunities

The vision uses AI in three fundamentally different roles, and conflating them is a design error. I separate them explicitly:

- **AI as Designer** (builds the agent) - the differentiating experience
- **AI as Worker** (the agent itself at runtime) - the product's function
- **AI as Operator's Assistant** (helps humans run the fleet) - underexploited in the vision, and a strong second-order differentiator

## 7.1 AI as Designer

### AI-1. Natural Language to Agent Graph **[STATED, CORE]**
- **What it does:** Converts a business description into a validated, executable agent specification.
- **Input:** User's description, the tenant's available tool catalog with capability descriptions, available knowledge bases, available node types, org policy constraints, and a library of reference patterns.
- **Output:** A schema-valid Agent Spec (nodes, edges, node configs, declared unknowns), plus a plain-language rationale per node.
- **Optional or core:** Core. This is the product's headline.
- **Recommended approach:** Frontier model with **constrained generation against a JSON schema**, plus a **validate-and-repair loop** (generate, validate against schema and against the real tool catalog, feed errors back, regenerate, maximum N attempts). Retrieve 3 to 5 similar reference agents as few-shot examples from a curated pattern library. Never let the model invent a tool: it may only reference tool IDs present in the supplied catalog, or emit an explicit `unconfigured_tool` node with a capability description.
- **Risks:** Hallucinated tools and fields, plausible-but-wrong workflows (this is the dangerous one, since a wrong graph looks correct), over-complex graphs, non-determinism across runs, latency of 20 to 60 seconds harming perceived quality.
- **Mitigations:** structural validation, capability-constrained generation, streaming output so waiting feels productive, a "why did you add this step" explanation per node, and a curated pattern library that carries most of the quality rather than raw model capability.

### AI-2. Conversational Graph Patching **[STATED, CORE]**
- **Input:** current spec, user instruction, edit history.
- **Output:** an ordered list of graph mutations plus a natural-language summary of the change.
- **Approach:** patch generation, never regeneration (see Section 2.1). Show a visual diff. All patches reversible.
- **Risks:** ambiguous instructions applied to the wrong node, silent loss of user config, cascading invalidation of downstream mappings.
- **Mitigation:** node disambiguation ("which approval did you mean?"), diff preview with accept/reject, automatic re-validation after patch.

### AI-3. Requirement Clarification **[RECOMMENDED]**
Ask up to three targeted questions before generating when the request is under-specified. Improves generation quality materially and makes the product feel consultative. Risk: an interrogation loop, so cap it hard.

### AI-4. Configuration Autofill / Schema Mapping **[RECOMMENDED, HIGH VALUE]**
Map agent data fields to a connector's actual API schema (for example, agent's `employee.start_date` to Workday's `hireDate`). This removes one of the most tedious blockers between a generated agent and a working one. Input: source schema, target schema, sample payload. Output: proposed field mapping with confidence, human confirms. Risk: silent mis-mapping, so require confirmation on any write action.

### AI-5. Test Case Generation **[RECOMMENDED]**
Generate realistic test inputs and edge cases from the agent spec and the connected schemas. Directly addresses the Section 26 "Test datasets" requirement, which otherwise requires the user to hand-write data they will not write.

## 7.2 AI as Worker (Runtime)

### AI-6. Task reasoning and tool selection **[STATED, CORE]**
- **Input:** node instructions, execution context, bound tool schemas, retrieved knowledge, memory.
- **Output:** tool calls and/or structured output.
- **Approach:** the model proposes, the **policy engine disposes**. Every tool call passes through a policy decision point that checks the agent's granted actions, the tenant's policy, and whether the action requires approval. The model must never be the security boundary.
- **Risks:** hallucinated arguments, wrong tool, loops, cost runaway, and **prompt injection from retrieved documents or tool outputs causing unauthorized actions**. The last one is the most serious risk in the entire product.
- **Mitigations:** allowlisted tools per agent, argument schema validation, step and cost budgets per execution, loop detection, treating all retrieved content and tool output as untrusted data (never as instructions), and mandatory human approval for high-impact actions.

### AI-7. Retrieval and query rewriting **[STATED, CORE]**
Rewrite the user question into effective retrieval queries, retrieve, rerank, cite. Risks: retrieval misses, stale documents, over-chunking losing context, and cross-tenant leakage if namespacing is wrong (a catastrophic failure mode, see Section 14).

### AI-8. Document understanding and extraction **[IMPLIED, CORE for named use cases]**
"Validate Documents" (S12, S25), invoice analysis (S3), contract analysis (S2) all require structured extraction from unstructured documents. Approach: multimodal extraction to a declared schema, with per-field confidence and a human review queue below a confidence threshold. Risk: silent extraction errors on financial data, which is why field-level confidence and thresholded escalation are not optional here.

### AI-9. Guardrail classifiers **[STATED as "Guardrails" in S26, undefined]**
Small, fast classifiers on inputs and outputs: PII detection and redaction, prompt-injection detection, off-topic or policy-violating content, toxicity. Should be a distinct, cheap model rather than the main agent, and must run on the path, not asynchronously.

### AI-10. Confidence-based escalation **[RECOMMENDED]**
The agent decides when to invoke a human, as Section 6 requires ("Ask humans for help"). Approach: explicit uncertainty signals (low extraction confidence, retrieval score below threshold, ambiguous instruction) rather than asking the model "are you confident", which is poorly calibrated.

## 7.3 AI as Operator's Assistant (largely absent from the vision)

### AI-11. Failure triage and root-cause summarization **[RECOMMENDED, STRONG DIFFERENTIATOR]**
Input: a cluster of failed traces. Output: "37 failures in the last hour share a cause: the Workday `hireDate` field changed format. Affected node: Create Employee Record. Suggested fix: update the mapping." This turns a debugging product into an operations product and is exactly the kind of thing the "Improve" step in Section 10 needs to mean.

### AI-12. Improvement recommendations from production data **[STATED as "Improve", undefined]**
Analyze successful and failed executions plus user feedback to propose spec changes: a better prompt, a missing branch, an unnecessary approval that is always approved (a strong signal it should be removed), a knowledge gap where retrieval consistently returns nothing. Present as a reviewable patch, reusing the AI-2 diff mechanism.

### AI-13. Cost and model optimization **[RECOMMENDED]**
Identify nodes where a cheaper model would produce equivalent results, backed by evaluation evidence rather than a guess. Directly monetizable and directly aligned to the cost tracking in Section 9.

### AI-14. Evaluation judging (LLM-as-judge) **[IMPLIED by S26]**
Score outputs against criteria for non-deterministic tasks where exact matching is impossible. Risk: judge bias and drift, so calibrate against human labels and version the judge prompt alongside the eval suite.

### AI-15. Marketplace matching **[RECOMMENDED, Phase 3]**
"I have this business problem" mapped to installable agents, which is a much better marketplace entry point than category browsing and reinforces the product's core metaphor.

## 7.4 Summary of AI risk posture

| Risk | Severity | Primary mitigation |
|---|---|---|
| Prompt injection causing unauthorized tool use | **Critical** | Policy engine outside the model, untrusted-content isolation, approval gates on impactful actions |
| Cross-tenant knowledge leakage via retrieval | **Critical** | Hard namespace isolation plus automated isolation tests in CI |
| Plausible-but-wrong generated workflow | High | Human review as a required step, explanation per node, validation gate before deploy |
| Non-determinism undermining trust | High | Test sets over single runs, pinned model versions, temperature control, eval gates |
| Cost runaway | Medium | Per-execution and per-tenant budgets, hard circuit breakers |
| Model provider outage or deprecation | Medium | Provider abstraction layer, fallback routing, pinned versions with a migration path |

---

# 8. Automation Opportunities

Processes that should be automated inside the platform rather than done by humans:

| # | Process | Automation | Trigger | Value | Phase |
|---|---|---|---|---|---|
| 1 | Document ingestion to retrievable knowledge | Parse, chunk, embed, index pipeline with status per document | Upload or scheduled sync | Core to Pillar 4 | MVP |
| 2 | Approval notification and reminders | Notify on suspend, remind before timeout, escalate on expiry | Execution state change, scheduler | Required by S15 | MVP |
| 3 | Scheduled agent runs | Cron-style triggers with timezone handling | Scheduler | The S3 example ("checks invoices every morning") requires it | MVP |
| 4 | Event-driven triggers from connected systems | Webhook receipt, verification, deduplication, mapping to an execution | External webhook | S25's "Employee Created" trigger requires it | MVP or Phase 2 |
| 5 | Credential refresh and expiry warning | Auto-refresh OAuth tokens, alert before expiry, block deploys with dead credentials | Scheduler | Prevents the most common production failure | MVP |
| 6 | Retry with backoff and dead-lettering | Automatic retry of transient failures, dead-letter for the rest | Execution failure | Reliability (S9) | MVP |
| 7 | Cost and token accounting | Per-step metering rolled up to execution, agent, workspace, tenant | Every model and tool call | S9 shows cost per execution | MVP |
| 8 | Trace capture | Automatic structured span emission from every node | Every execution | S16 mandates it | MVP |
| 9 | Pre-deploy validation | Schema, credentials, permissions, unreachable nodes, missing config, test pass | Deploy request | S14 shows this gate | MVP |
| 10 | Alerting on SLO breach | Failure rate, latency, cost, queue depth thresholds | Metrics pipeline | Operations | Phase 2 |
| 11 | Evaluation runs on version change | Run the eval suite automatically when a version is created | Version creation | Regression prevention | Phase 2 |
| 12 | Knowledge re-sync and re-index | Periodic re-crawl of connected sources, incremental re-embedding | Scheduler | Prevents stale answers | Phase 2 |
| 13 | Usage-based billing calculation | Meter to invoice | Billing cycle | Commercial requirement | Phase 2 |
| 14 | Data retention enforcement | Purge traces and payloads past the tenant's retention window | Scheduler | GDPR | Phase 2 |
| 15 | Anomaly detection on agent behavior | Flag sudden changes in tool-call patterns or output distribution | Continuous | Security and quality | Phase 3 |
| 16 | Automated tenant isolation testing | Continuous cross-tenant access probes in CI and staging | CI, scheduled | Highest-severity risk needs continuous proof | MVP (as engineering practice) |

**[RECOMMENDED] Engineering-side automation** (internal, not product features): CI/CD with per-PR ephemeral environments, contract tests against recorded connector fixtures, nightly AI generation-quality benchmarks with alerting on regression, infrastructure as code, automated dependency and container scanning, and automated load tests for the execution engine.

---

# 9. Integrations

## 9.1 Integration Strategy (the most important recommendation in this section)

**[RECOMMENDED] Adopt a three-tier connector strategy rather than building N bespoke integrations.** Section 7 names eleven categories; naive implementation is an unbounded engineering commitment.

- **Tier 1: MCP-first.** Treat MCP as the platform's native tool interface. Any system with an MCP server is supported with zero bespoke work. Internally, wrap first-party connectors as MCP servers too, so there is exactly one tool interface in the runtime.
- **Tier 2: Curated first-party connectors** for the highest-value systems, built as internal MCP servers with hand-tuned schemas, auth handling and tested action coverage. Start with at most five, chosen by the design-partner's actual stack.
- **Tier 3: Generic escape hatches** so no customer is ever blocked: an HTTP/REST connector (define base URL, auth, endpoints, schemas), a SQL connector (read-only by default), a webhook trigger, and an outbound webhook action.

This makes the integration surface a product decision rather than a headcount decision, and it directly delivers the Section 7 promise that customers do not write custom integration code per agent.

## 9.2 Integration Register

| System | Why required | API / service | Auth | Data exchanged | Trigger / events | Technical risks |
|---|---|---|---|---|---|---|
| **Identity Provider (Okta, Entra ID, Google)** | Enterprise SSO and provisioning. **[GAP] not in vision but mandatory for enterprise sale** | SAML 2.0, OIDC, SCIM 2.0 | Federated | User identity, group to role mapping | Login, user lifecycle | Per-IdP quirks, group mapping complexity, JIT provisioning edge cases |
| **LLM providers (Anthropic, OpenAI, Azure OpenAI, Bedrock)** | The intelligence layer | REST, streaming | API key or IAM, per-tenant keys optional | Prompts, context, completions, token counts | Every model call | Rate limits, outages, deprecation, cost variance, data-residency and no-training guarantees |
| **Embedding provider** | Knowledge indexing | REST | API key | Document chunks, vectors | Ingestion, query | Changing models forces full re-index, cost at scale |
| **Slack** | Notifications, approvals, agent surface | Web API, Events API, Block Kit, interactivity | OAuth 2.0 (bot + user tokens) | Messages, approval actions, user identity | Outbound notify, inbound events, interactive callbacks | Rate limits, 3-second interaction ACK, workspace vs org install, token rotation |
| **Microsoft Teams** | Same, explicitly named in S7 example | Graph API, Bot Framework, Adaptive Cards | Azure AD OAuth, app registration | Messages, cards, approvals | Same | Tenant admin consent friction, app publishing process, more complex than Slack |
| **Email (SMTP/IMAP, Graph, Gmail)** | Notifications, approvals, and email-triggered agents | SMTP, Graph, Gmail API | OAuth 2.0 or SMTP creds | Messages, attachments | Send, and inbound as trigger | Deliverability, spoofing risk on approve-by-email, attachment handling, threading |
| **Accounting (QuickBooks, Xero, NetSuite)** | Explicit S7 example (invoice agent) | REST | OAuth 2.0 | Invoices, vendors, payments | Poll or webhook | Financial data sensitivity, write actions are irreversible, sandbox parity, rate limits |
| **HRIS (Workday, BambooHR, SuccessFactors)** | Required by the S25 golden path | REST, SOAP for Workday | OAuth 2.0 or WS-Security | Employee records, org structure | Employee created events | Workday complexity is high, custom tenant schemas, PII sensitivity, slow procurement |
| **CRM (Salesforce, HubSpot, Dynamics)** | Lead qualification agent (S2) | REST | OAuth 2.0 | Leads, contacts, opportunities, activities | Record change events | Heavy customization per tenant, API call limits, field-level security must be respected |
| **ERP (SAP, Oracle, Dynamics)** | Named in S7 | Varies widely, often on-prem | Varies | Orders, invoices, master data | Poll or event | Frequently not internet-facing, needs a gateway, long integration cycles, highest risk item on this list |
| **Ticketing (Jira Service Management, ServiceNow, Zendesk)** | IT helpdesk and incident agents | REST | OAuth or API token | Tickets, comments, status | Ticket events | Workflow state machines differ per tenant |
| **Databases (Postgres, MySQL, SQL Server)** | Named in S7 | Native drivers | Credentials or IAM | Query results, writes | Query, CDC | Direct DB access is a serious security exposure, needs read-only defaults, network reachability, injection prevention |
| **WhatsApp** | Named in S7 | WhatsApp Business Cloud API | Meta OAuth, permanent tokens | Messages, templates | Inbound and outbound | Template pre-approval, 24-hour session window, per-message cost, business verification delays |
| **Document storage (SharePoint, Google Drive, Box, S3)** | Knowledge sources | Graph, Drive API, S3 | OAuth 2.0 or IAM | Documents, permissions metadata | Sync, change notifications | **Permission mirroring**: if a user cannot read a document in SharePoint, the agent must not surface it, which is a genuinely hard problem |
| **MCP servers (customer-supplied)** | Explicit S7 requirement | MCP over HTTP/SSE or stdio | Varies, often OAuth | Tool schemas, calls, results | Discovery, invocation | **Tool-description injection**, schema drift, unvetted third-party servers, no standard authorization granularity, latency |
| **Observability (OpenTelemetry, Datadog)** | Internal ops, plus customer SIEM export | OTLP, vendor APIs | API key | Traces, metrics, logs | Continuous | Cardinality and cost explosion from per-execution traces |
| **Billing (Stripe)** | Commercial requirement, **[GAP] not in vision** | REST, webhooks | API key | Usage, subscriptions, invoices | Billing cycle | Metering accuracy disputes |

## 9.3 Cross-cutting integration risks

1. **Reachability.** ERPs and databases are often behind a firewall. **[GAP]** The vision assumes cloud-to-cloud. A lightweight customer-installed gateway or agent may be required, which is a significant scope addition.
2. **Write actions are not transactional.** If an agent creates an employee record and then a later step fails, there is no rollback. Compensating actions must be a first-class concept in the runtime, not an afterthought.
3. **Permission fidelity.** The agent's effective permissions in a downstream system must be at least as restrictive as the requesting user's. Otherwise the platform becomes a privilege-escalation vector, which is the fastest way to fail a security review.
4. **Sandbox availability.** Several enterprise systems have poor or no sandbox environments, which is another argument for platform-level dry-run and mocking.

---

# 10. MCP Opportunities

MCP appears twice in the vision: as a system agents can connect to (S7), and as something the user should never need to understand (S3), plus as a configurable item in the first release (S26). There are actually **three distinct MCP roles**, and separating them is important.

## 10.1 Role 1: Platform as MCP Client (product feature, high value) **[STATED]**

The platform consumes MCP servers as tool sources.

- **Value:** every MCP server in the ecosystem becomes a supported integration with no bespoke connector work. This is the single highest-leverage integration decision available, and it directly delivers the Section 7 promise.
- **Design:** register a server (URL plus auth), discover its tool manifest, cache and version the schemas, expose tools in the builder's tool picker with human-readable descriptions, bind selected tools to agents with action-level scope, invoke through the same policy decision point as native tools.
- **Recommendation:** make MCP the **internal** tool interface too. First-party connectors become internal MCP servers. One invocation path, one schema format, one policy enforcement point, one trace format.
- **Risks specific to MCP:**
  - **Tool-description injection.** A malicious or compromised MCP server can put instructions in its tool descriptions, which enter the model's context. Mitigation: treat tool descriptions as untrusted, sanitize, pin approved schema versions, alert on schema change, and require admin approval before a new or changed server is usable in production.
  - **Schema drift.** A server changes a tool's signature and deployed agents break silently. Mitigation: version pinning plus scheduled schema-diff checks.
  - **Authorization granularity.** MCP does not standardize fine-grained authz. Mitigation: enforce scope at the platform's policy layer, never rely on the server.
  - **Availability and latency.** Customer-hosted servers may be slow or down. Mitigation: timeouts, circuit breakers, health checks surfaced in the connections UI.
  - **Untrusted third-party servers.** Mitigation: an allowlist with admin approval, and a registry of vetted servers.

## 10.2 Role 2: Platform as MCP Server (product feature, differentiator) **[RECOMMENDED, not in vision]**

Expose the platform's own capabilities as an MCP server so external AI clients (Claude Desktop, IDEs, other agent frameworks, the customer's own agents) can use them.

Tools worth exposing: `list_agents`, `invoke_agent`, `get_execution_status`, `search_knowledge`, `list_pending_approvals`.

- **Why this matters strategically:** it inverts the integration burden. Instead of the platform needing to connect to everything, everything can connect to the platform. It also makes deployed agents callable from wherever employees already work, which partly answers the **[GAP]** in Section 4.6 about the end-consumer surface.
- **Risks:** authentication and per-tenant scoping for external clients, and the risk of the platform becoming a confused deputy if an external client can invoke high-privilege agents. Requires scoped API tokens with explicit agent allowlists.

## 10.3 Role 3: MCP for Internal Engineering Productivity (not a product feature)

Useful for the team building the platform, and worth separating clearly from product scope so they are not confused in planning:

| MCP server | Value to the build team |
|---|---|
| **Jira / Linear** | Generate tickets from this analysis, keep specs and tickets in sync, status rollups |
| **GitHub** | PR review assistance, changelog generation, linking commits to requirements |
| **Slack** | Standup summaries, incident triage support |
| **Google Drive / Notion** | Keep the spec, this document and the design decisions retrievable during development |
| **Postgres (read-only, dev)** | Debugging and data exploration during development, never against production |
| **Sentry / Datadog** | Incident investigation |

## 10.4 Custom MCP servers worth building

1. **Internal Tool Gateway MCP** wrapping the customer's internal APIs, deployable inside their network. This elegantly solves the on-prem reachability gap from Section 9.3.
2. **Knowledge MCP** exposing tenant knowledge bases as a standard retrieval tool, reusable by both internal agents and external clients.
3. **Approval MCP** so approvals can be surfaced in any MCP-capable client.

**[ANALYSIS]** Note the tension with Section 3: the user "should not need to understand MCP", yet Section 26 lists MCP configuration in the first release. The resolution is persona-based: the **Technical Steward** registers MCP servers, and the **Business Author** simply sees tools called "Create Employee Record" with no MCP terminology anywhere in their UI. The word "MCP" should not appear in the business author's interface at all.

---

# 11. Technical Architecture

## 11.1 The Five Decisions That Determine Whether the Prototype Survives

Section 21 states the prototype must not require a rewrite to become production. That outcome depends almost entirely on five decisions made at the start. Everything else can be refactored later.

**Decision 1: The Agent Spec is the single source of truth.**
A declarative, versioned, JSON-schema-defined document describing nodes, edges, configuration, bindings and policies. Every subsystem reads or writes this one artifact: the AI designer emits it, the canvas renders it, the runtime executes it, the version system diffs it, the marketplace packages it, the evaluator tests it, the validator checks it. If the canvas and the runtime ever hold separate representations, they will diverge and the product's central promise ("what you see is what runs") breaks. This is the most important decision in the document.

**Decision 2: Execution must be durable from day one.**
Human approval with timeouts and escalation (S15) means executions live for days. Every step must be checkpointed, resumable, and idempotent, with the process able to die and recover. Retrofitting durability onto a synchronous engine is a rewrite. Use a durable workflow engine (Temporal is the mature choice; a Postgres-backed state machine with a job queue is a defensible lighter-weight alternative for the prototype **provided** the step-checkpointing model is correct from the start).

**Decision 3: A policy decision point sits between the model and every tool call.**
The model proposes an action; a deterministic policy engine authorizes it against the agent's grants, the tenant's policy and the approval rules. The model is never the security boundary. Bolting this on later means auditing every call site.

**Decision 4: Tenant isolation is enforced at the data layer, not the application layer.**
Postgres row-level security keyed on tenant, per-tenant vector namespaces, per-tenant encryption keys for credentials. Application-layer `WHERE tenant_id = ?` filtering fails eventually because it depends on every developer remembering. This is a Section 20 hard requirement and a company-ending failure if breached.

**Decision 5: Traces are structured product data, not logs.**
Section 16 lists ten mandatory questions per execution. That is a queryable data model with a retention policy and access control, not text in a log aggregator.

## 11.2 Component Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│  CLIENTS                                                          │
│  Web app (builder, canvas, monitoring, admin)                     │
│  Chat surfaces (Slack / Teams / email)   Public API + SDK (P3)    │
└──────────────────────────┬────────────────────────────────────────┘
                           │ HTTPS / WebSocket (live execution)
┌──────────────────────────▼────────────────────────────────────────┐
│  API GATEWAY / BFF                                                │
│  AuthN, tenant resolution, rate limiting, request validation      │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  CONTROL PLANE (synchronous, request/response)                    │
│  ┌────────────┬────────────┬────────────┬────────────┐            │
│  │ Agent      │ Design AI  │ Knowledge  │ Connection │            │
│  │ Service    │ Service    │ Service    │ Service    │            │
│  ├────────────┼────────────┼────────────┼────────────┤            │
│  │ Deploy &   │ Identity & │ Policy /   │ Trace &    │            │
│  │ Version    │ RBAC       │ Governance │ Analytics  │            │
│  └────────────┴────────────┴────────────┴────────────┘            │
└──────────────────────────┬────────────────────────────────────────┘
                           │ enqueue / signal
┌──────────────────────────▼────────────────────────────────────────┐
│  DATA PLANE (asynchronous, durable)                               │
│                                                                   │
│  Durable Execution Engine                                         │
│    • per-step checkpointing, retries, timers, signals             │
│    • suspend/resume for human approval                            │
│                                                                   │
│  Node Executors:  Trigger | LLM Agent | Knowledge | Condition |    │
│                   Tool | Approval | Notification | Transform      │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐     │
│  │ Model Router │  │ POLICY       │  │ Tool Invocation Layer│     │
│  │ (multi-      │→ │ DECISION     │→ │  (all tools are MCP) │     │
│  │  provider)   │  │ POINT        │  │  sandbox + egress    │     │
│  └──────────────┘  └──────────────┘  └──────────────────────┘     │
│                                                                   │
│  Ingestion Workers (parse → chunk → embed → index)                │
│  Scheduler (cron triggers, timeouts, escalations, retention)      │
│  Webhook Receiver (verify, dedupe, map, enqueue)                  │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  DATA & INFRASTRUCTURE                                            │
│  Postgres (RLS)  │ Vector store │ Object storage │ Redis          │
│  Event log (traces, append-only) │ Secret vault (KMS)             │
│  Metrics + OpenTelemetry                                          │
└───────────────────────────────────────────────────────────────────┘
```

## 11.3 Layer-by-layer recommendations

| Layer | Recommendation | Why (not just preference) |
|---|---|---|
| **Frontend** | React with TypeScript, a mature graph library (React Flow or similar) for the canvas, WebSocket or SSE for live execution state | The canvas is the product. Building a graph editor from scratch is months of work with no differentiation. Live node state (S13) requires push, not polling |
| **Backend** | A **modular monolith** in one language (TypeScript or Python), with clear service boundaries internally, deployed as two processes: control plane and workers | Microservices at prototype stage add distributed-systems cost with no benefit. The boundaries above are logical, and can be split later along already-clean seams. Section 21 asks for no rewrite, not for premature distribution |
| **Language choice** | Python for the AI/execution plane if the team's strength is ML; TypeScript end to end if the team's strength is product engineering | **[ASSUMPTION]** team composition unknown. This should be decided by existing skill, not fashion. A polyglot split (TS control plane, Python workers) is legitimate but doubles the toolchain cost |
| **Database** | PostgreSQL as the primary store, with row-level security, JSONB for agent specs, and partitioned tables for executions and trace spans | One database that handles relational, JSON and (via pgvector) vectors keeps the prototype simple while remaining production-viable. Partitioning matters because traces will be the largest table by an order of magnitude |
| **Vector store** | pgvector initially, with a repository abstraction so a dedicated store can replace it | Avoids a second datastore early. The abstraction is cheap now, expensive later. Migrate when scale or hybrid-search needs demand it, not before |
| **Durable execution** | Temporal, or a Postgres-backed state machine with a well-defined checkpoint model | Non-negotiable capability (Decision 2). Buy versus build is a genuine trade: Temporal is operationally heavier but correct; a custom engine is simpler now and risks re-implementing Temporal badly |
| **Queue / cache** | Redis for cache, ephemeral state, rate limiting and pub/sub of live execution events | Standard, and already needed for WebSocket fan-out |
| **AI layer** | A provider-abstracted model router (Anthropic, OpenAI, Azure, Bedrock) with per-tenant key support, model pinning, streaming, retries, fallback and token accounting | Enterprises will demand specific providers, regions and no-training guarantees. Hard-coding one provider is a commercial dead end |
| **MCP layer** | An MCP client service handling registration, schema discovery, caching, versioning, invocation and health. All tools, including first-party, exposed through it | Single tool interface (Section 10.1). One place to enforce policy and emit traces |
| **Auth** | OIDC-based session auth for the app, SAML/OIDC SSO plus SCIM for enterprise, scoped API keys for programmatic access, short-lived signed tokens for approval deep links | Approval links sent by email must be single-use and expiring, or approval becomes forgeable |
| **Authorization** | Centralized policy service, permission checks at the API layer and again at the tool-invocation layer, RLS as the backstop | Defence in depth is warranted given the blast radius of a permission bug |
| **Secrets** | Dedicated vault or cloud KMS with envelope encryption and per-tenant data keys. Specs store references, never values | Section 20 lists Credentials as an isolation boundary |
| **File storage** | S3-compatible object storage, per-tenant prefixes, server-side encryption, signed time-limited URLs | Standard, plus the per-tenant prefix supports deletion and residency later |
| **Notifications** | A single notification service with pluggable channels (email, Slack, Teams, in-app, webhook), templating and delivery tracking | Approval flows depend on delivery. Undelivered approvals are stuck executions |
| **Observability** | OpenTelemetry for system telemetry, plus a **separate, first-class execution trace store** for the product-facing trace | Two different consumers: engineers debugging the platform, and customers auditing agents. Conflating them produces a trace UI that leaks internals and an ops view cluttered with business data |
| **Deployment** | Containers on managed Kubernetes or equivalent, IaC, separate control-plane and worker scaling, per-tenant rate limits | Workers scale with execution volume, control plane with user count. These diverge quickly |

## 11.4 Technologies deliberately NOT recommended yet

Per the instruction not to introduce technology without clear reason: no microservices mesh, no Kafka (Postgres plus Redis is sufficient until sustained event volume justifies it), no separate graph database (the graph is small and lives in the spec), no fine-tuning infrastructure, no self-hosted model serving, no multi-cloud, no dedicated feature store, no separate search cluster. Each of these should be introduced only when a measured constraint demands it.

---

# 12. Data Model

## 12.1 Core Entities

**Tenancy & Identity**
- `Tenant` (organization, the isolation boundary): plan, region, retention policy, SSO config, status
- `Workspace`: belongs to Tenant, the scoping unit for agents, connections and knowledge
- `User`: belongs to Tenant, identity, SSO subject, status
- `Membership`: User to Workspace with Role
- `Role` and `Permission`: system roles in MVP, custom roles later
- `ApiKey`: scoped programmatic access

**Agent Definition**
- `Agent`: logical agent, owner, workspace, name, description, criticality, status
- `AgentVersion`: immutable, holds the full `spec` JSONB, created_by, created_at, changelog, parent_version, source (ai_generated / manual / template / marketplace)
- `AgentSpec` (embedded JSONB, schema-validated): nodes, edges, node configs, tool bindings, knowledge bindings, model config, guardrails, output schema, triggers
- `SpecPatch`: an individual AI or manual mutation applied to a draft, enabling diff, undo and audit of who changed what
- `Template`: seed specs
- `Trigger`: type (manual, schedule, webhook, event, api), config, enabled, belongs to a deployment

**Connections & Tools**
- `Connection`: a configured link to an external system (or a registered MCP server), workspace-scoped, auth type, status, health
- `Credential`: encrypted secret material, references a Connection, never exposed after write
- `ToolDefinition`: a discovered or declared tool (name, description, input schema, output schema, side-effect classification: read / write / irreversible)
- `ToolGrant`: which Agent may call which ToolDefinition, with constraints (allowed fields, value limits, approval-required flag)

**Knowledge**
- `KnowledgeBase`: workspace-scoped, embedding model, chunking config, access policy
- `Document`: source, filename, checksum, version, ingestion status, source permissions metadata
- `Chunk`: text, position, metadata, document reference
- `Embedding`: vector, chunk reference, tenant namespace
- `KnowledgeBinding`: Agent to KnowledgeBase, with retrieval config

**Memory** (**[GAP]** definition pending)
- `MemoryStore` and `MemoryRecord`: scope (execution / user / agent / workspace), key, value, embedding, TTL

**Runtime**
- `Deployment`: AgentVersion deployed to an Environment, status, deployed_by, deployed_at
- `Environment`: staging, production (per workspace), with its own connection bindings
- `Execution`: deployment, agent_version (pinned), trigger source, initiator, status, started/ended, duration, total cost, input, output, error
- `ExecutionStep`: execution, node reference, sequence, status, input, output, model used, tokens, cost, latency, error, retry count
- `TraceSpan`: fine-grained events within a step (model call, retrieval, tool call, policy decision), with redaction applied per policy
- `ApprovalRequest`: execution, step, approver(s) or role, context payload, proposed action, status, deadline, escalation chain
- `ApprovalDecision`: approver, decision, reason, timestamp, payload hash, immutable

**Evaluation**
- `EvalSuite`, `EvalCase` (input, expected, assertions), `EvalRun` (suite, agent_version, results, score, pass/fail)

**Governance & Commercial**
- `AuditLog`: append-only, actor, action, resource, before/after, IP, timestamp
- `PolicyRule`: tenant or workspace scoped, for example "any tool with side_effect=irreversible requires approval"
- `UsageRecord`: metered units (tokens, executions, storage) for billing and cost attribution
- `Notification`: recipient, channel, template, payload, delivery status

**Marketplace (Phase 3)**
- `Listing`, `ListingVersion` (packaged spec plus config contract plus eval suite plus knowledge templates), `Installation` (tenant, listing version, resulting local Agent, config mapping)

## 12.2 Key Relationships and the reasoning behind them

```
Tenant 1──N Workspace 1──N Agent 1──N AgentVersion
                                          │
                          Deployment N──1 ┘   (a version may be deployed
                              │                to several environments)
                              │
                              1
                              │
                              N
                          Execution 1──N ExecutionStep 1──N TraceSpan
                              │                │
                              │                └──0..1 ApprovalRequest 1──N ApprovalDecision
                              │
                              └── references pinned AgentVersion (immutably)

Workspace 1──N Connection 1──N ToolDefinition N──N Agent  (via ToolGrant)
Workspace 1──N KnowledgeBase N──N Agent (via KnowledgeBinding)
Tenant 1──N User N──N Workspace (via Membership, carrying Role)
```

**Non-obvious modelling decisions that matter:**

1. **Execution pins AgentVersion, not Agent.** Without this, a trace from three months ago cannot be interpreted, because the agent has changed. Section 16's trust requirement is unsatisfiable otherwise.
2. **AgentVersion is immutable; drafts are separate.** Editing produces a draft, publishing produces a version. Deployments only ever reference versions.
3. **Knowledge is workspace-scoped, not agent-scoped.** Section 8 explicitly requires one KB serving many agents.
4. **Credentials are referenced from the spec, never embedded.** This makes specs safely exportable to the marketplace and diffable in the UI without leaking secrets.
5. **Environments own connection bindings.** The same agent version must hit sandbox QuickBooks in staging and production QuickBooks in production, with no spec change. If the spec hard-codes the connection, promotion is impossible.
6. **Tool definitions carry a side-effect classification** (read / write / irreversible). This single field drives dry-run behavior, default approval policy and risk scoring, and adding it later means reclassifying every tool.
7. **Marketplace install copies rather than references.** A live reference to a vendor-controlled spec would mean a third party can silently change what runs inside a customer's tenant, which is unacceptable in an enterprise context.

---

# 13. API Requirements

Grouped by module. All endpoints are tenant-scoped by the authenticated context; tenant is never a client-supplied parameter.

**Authentication & Identity**
```
POST   /auth/login
POST   /auth/logout
POST   /auth/refresh
GET    /auth/me
GET    /auth/sso/{tenant}/initiate
POST   /auth/sso/callback
POST   /auth/api-keys          GET /auth/api-keys        DELETE /auth/api-keys/:id
```

**Tenants & Workspaces**
```
GET    /tenant                 PATCH /tenant
GET    /tenant/settings        PATCH /tenant/settings
GET    /workspaces             POST /workspaces
GET    /workspaces/:id         PATCH /workspaces/:id     DELETE /workspaces/:id
GET    /workspaces/:id/members POST /workspaces/:id/members
```

**Users & Access Control**
```
GET    /users                  POST /users/invite
GET    /users/:id              PATCH /users/:id          DELETE /users/:id
GET    /roles                  POST /roles               PATCH /roles/:id
GET    /users/:id/permissions
POST   /permissions/check      (internal policy evaluation)
```

**Agents & Versions**
```
GET    /agents                 POST /agents
GET    /agents/:id             PATCH /agents/:id         DELETE /agents/:id
POST   /agents/:id/duplicate
GET    /agents/:id/versions    POST /agents/:id/versions        (publish a draft)
GET    /agents/:id/versions/:v
GET    /agents/:id/versions/diff?from=&to=
POST   /agents/:id/validate                                     (pre-deploy gate)
GET    /agents/:id/draft       PUT  /agents/:id/draft
POST   /agents/:id/draft/patch                                  (apply graph mutations)
POST   /agents/:id/draft/undo
```

**AI Design Service**
```
POST   /design/generate        (description → spec, streaming)
POST   /design/clarify         (ambiguous request → questions)
POST   /design/patch           (instruction + spec → mutations + diff, streaming)
POST   /design/explain         (spec or node → plain-language explanation)
POST   /design/suggest-mapping (source schema + target schema → field mapping)
POST   /design/generate-tests  (spec → test cases)
GET    /templates              GET /templates/:id
```

**Connections & Tools**
```
GET    /connections            POST /connections
GET    /connections/:id        PATCH /connections/:id    DELETE /connections/:id
POST   /connections/:id/test
POST   /connections/:id/rotate
GET    /connections/:id/dependents          (which agents would break)
GET    /oauth/:provider/authorize
GET    /oauth/:provider/callback
GET    /tools                              (catalog, filtered by grants)
GET    /tools/:id/schema
POST   /mcp/servers            GET /mcp/servers          DELETE /mcp/servers/:id
POST   /mcp/servers/:id/discover           (refresh tool manifest)
GET    /mcp/servers/:id/health
POST   /agents/:id/tool-grants  GET /agents/:id/tool-grants
```

**Knowledge**
```
GET    /knowledge-bases        POST /knowledge-bases
GET    /knowledge-bases/:id    PATCH /knowledge-bases/:id  DELETE /knowledge-bases/:id
POST   /knowledge-bases/:id/documents            (multipart upload)
GET    /knowledge-bases/:id/documents
GET    /knowledge-bases/:id/documents/:docId     DELETE .../:docId
POST   /knowledge-bases/:id/documents/:docId/reindex
POST   /knowledge-bases/:id/query                (retrieval playground)
POST   /knowledge-bases/:id/sync                 (connector-sourced refresh)
```

**Deployment**
```
GET    /environments
POST   /agents/:id/deploy          { version, environment }
GET    /agents/:id/deployments
POST   /deployments/:id/rollback
POST   /deployments/:id/pause      POST /deployments/:id/resume
DELETE /deployments/:id
GET    /deployments/:id/triggers   POST /deployments/:id/triggers
```

**Execution & Runtime**
```
POST   /agents/:id/run                    (manual / test run, supports dryRun flag)
POST   /invoke/:deploymentId              (production invocation)
GET    /executions                        (filter: agent, status, date, initiator)
GET    /executions/:id
GET    /executions/:id/steps
GET    /executions/:id/trace
GET    /executions/:id/stream             (SSE/WebSocket for live canvas)
POST   /executions/:id/cancel
POST   /executions/:id/retry              POST /executions/bulk-retry
POST   /webhooks/:triggerToken            (public, signature-verified inbound trigger)
```

**Approvals**
```
GET    /approvals                         (my pending approvals)
GET    /approvals/:id
POST   /approvals/:id/approve             { reason? }
POST   /approvals/:id/reject              { reason }
POST   /approvals/:id/delegate            { toUserId }
GET    /approvals/token/:signedToken      (out-of-app deep link, single-use)
POST   /approvals/token/:signedToken/decide
```

**Evaluation & Testing**
```
GET    /agents/:id/eval-suites   POST /agents/:id/eval-suites
POST   /eval-suites/:id/cases    PATCH /eval-cases/:id
POST   /eval-suites/:id/run      { agentVersion }
GET    /eval-runs/:id            GET /eval-runs/:id/results
GET    /eval-runs/compare?a=&b=
```

**Monitoring, Cost & Audit**
```
GET    /analytics/overview
GET    /analytics/agents/:id
GET    /analytics/costs         (group by agent | workspace | model | connector)
GET    /analytics/errors
GET    /audit-logs              (filter, paginate, export)
GET    /usage                   (metering)
GET    /alerts                  POST /alerts   PATCH /alerts/:id
```

**Notifications**
```
GET    /notifications           POST /notifications/:id/read
GET    /notification-settings   PATCH /notification-settings
```

**Marketplace (Phase 3)**
```
GET    /marketplace/listings           GET /marketplace/listings/:id
POST   /marketplace/listings/:id/install
GET    /marketplace/installations      POST /marketplace/installations/:id/update
POST   /marketplace/publish            (publisher)
```

**Design conventions [RECOMMENDED]:** cursor pagination on all list endpoints, `Idempotency-Key` required on every state-changing runtime call (trigger deduplication depends on it), consistent RFC 7807 problem-details error format, per-tenant and per-endpoint rate limits, API versioning via URL prefix from day one, and SSE rather than polling for live execution state.

---

# 14. Security

Section 20 sets the hard requirement: no tenant may ever access another tenant's agents, knowledge, credentials, executions, users, logs or business data. Section 17 requires permissions at six levels. This section translates those into engineering requirements.

## 14.1 Authentication
- OIDC-based sessions with short-lived access tokens and rotating refresh tokens; secure, httpOnly, sameSite cookies.
- Enterprise SSO via SAML 2.0 and OIDC, with SCIM 2.0 for provisioning and, critically, **deprovisioning** (**[GAP]** absent from the vision, blocking for enterprise deals).
- MFA enforcement policy at tenant level.
- Scoped API keys with expiry and rotation, shown once.
- Signed, single-use, expiring tokens for out-of-app approval links. An approval link that can be replayed or forwarded is a governance failure.

## 14.2 Authorization
- RBAC with permissions evaluated centrally, enforced at the API boundary **and again** at the tool-invocation layer.
- Resource-scoped grants across all six levels required by Section 17: user, workspace, agent, knowledge, tool, action.
- **Agent runtime identity is separate from user identity**, with a clear, audited answer to whose credentials an agent uses (see Section 3.2).
- **Effective-permission ceiling:** an agent invoked by a user must never exceed that user's own permissions in downstream systems, or the platform becomes a privilege-escalation path.
- Segregation of duties: the requester of an action cannot approve it.

## 14.3 Multi-Tenancy and Data Isolation
- Postgres **row-level security** with a session-level tenant context set by middleware, so isolation does not depend on individual queries being written correctly.
- Per-tenant vector namespaces or collections; retrieval filters applied at the store, not post-retrieval.
- Per-tenant object-storage prefixes with IAM policies.
- Per-tenant encryption keys for credentials (envelope encryption with KMS), so a key compromise is scoped.
- Per-tenant rate limits and execution quotas to prevent noisy-neighbor denial of service.
- **[RECOMMENDED] An automated cross-tenant isolation test suite that runs in CI on every commit**, attempting access to another tenant's resources through every API and every retrieval path. Isolation cannot be verified by code review alone.
- **[ASSUMPTION]** Shared-infrastructure multi-tenancy is acceptable to the target customers. Some regulated enterprises require dedicated infrastructure or VPC deployment; this is a commercial question with major architectural consequences and should be asked of design partners early.

## 14.4 AI-Specific Security (the highest-severity area)
- **Prompt injection defence.** Retrieved documents, tool outputs, MCP tool descriptions and end-user input are all untrusted. They must be structurally delimited in the context, never treated as instructions, and the model's ability to act must be constrained externally by the policy engine rather than by prompt wording.
- **No model-as-security-boundary.** Every tool call authorized deterministically.
- **Data egress control.** Tenant policy governs which model providers may see tenant data, in which region, with what retention and no-training guarantees. Enterprises will ask this in the first security review.
- **Output validation** against declared schemas before values flow into a tool call.
- **Execution budgets:** maximum steps, maximum tool calls, maximum spend, maximum wall-clock, enforced as hard circuit breakers.
- **Sandboxed tool execution** with an egress allowlist, so a compromised or malicious connector cannot reach arbitrary destinations.

## 14.5 Secrets Management
Vault or KMS-backed storage, envelope encryption, no plaintext secrets in the database, in logs, in traces, in agent specs, or in LLM context. Automatic rotation support, revocation propagation, and an access audit on every secret read.

## 14.6 Data Protection and Privacy
- TLS 1.3 in transit, AES-256 at rest.
- **Field-level redaction in traces.** Section 16 requires recording "what data was sent", which directly conflicts with data minimisation when that data is PII. Resolution: store a redacted trace by default, with the full payload access-controlled, separately audited and subject to a shorter retention window.
- Configurable retention per tenant with automated purge.
- GDPR support: export, deletion (including from vector indexes and traces, which is technically the hard part), processing records, DPA, sub-processor list.
- **[GAP]** Data residency is not mentioned but will be required by EU and increasingly other customers.

## 14.7 API and Infrastructure Security
Rate limiting per tenant, user and endpoint; strict input validation; webhook signature verification and replay protection; CORS restrictions; CSP and standard security headers; dependency and container scanning in CI; least-privilege service accounts; network segmentation between control plane, workers and data stores; secrets never in environment variables in plaintext at rest.

## 14.8 Audit Logging
Append-only, tamper-evident (hash-chained is worth considering given the compliance positioning), covering: authentication events, permission changes, connection and credential lifecycle, agent create/edit/version/deploy/rollback, every approval decision, every tool invocation with its policy decision, data exports, and admin impersonation. Retention aligned to the customer's compliance regime, exportable to the customer's SIEM.

## 14.9 Compliance Readiness
**[GAP]** Not mentioned anywhere in the vision, but SOC 2 Type II is a near-universal prerequisite for enterprise SaaS purchase, and the named use cases (finance, HR, legal) pull in GDPR and possibly HIPAA and SOX considerations. Compliance requirements shape the architecture (audit, retention, access control, encryption, vendor management), so they should be scoped now even if certification comes later. Retrofitting is significantly more expensive.

---

# 15. Edge Cases and Failure Scenarios

## 15.1 Agent Creation

| Scenario | Expected behavior | Error handling | User message |
|---|---|---|---|
| Request too vague ("automate my work") | Ask up to 3 clarifying questions, then generate a best-effort draft | Never a hard refusal | "I can help. Which process should this handle, and what should trigger it?" |
| Requested capability has no matching tool | Create the node as unconfigured with a capability description | Node marked with a TODO badge | "This step needs a connection to your HR system. Connect one, or use a custom API connection." |
| AI produces an invalid graph | Auto-repair loop, up to N attempts; if still invalid, return the closest valid subset plus a note | Log for quality monitoring | "I built most of this. One step needs your input." |
| Generation exceeds timeout | Stream partial results, offer continue | Cancel cleanly, no orphaned draft | "Still working. You can keep waiting or start from a template." |
| Request is out of scope or prohibited (for example an agent to auto-approve its own payments) | Refuse with the policy reason | Audit the attempt | "This would bypass approval requirements set by your admin." |
| Two users edit the same draft concurrently | Optimistic locking with version check; second writer sees a conflict view | No silent overwrite | "This agent was changed by Priya 2 minutes ago. Review the differences." |
| AI patch would delete user-configured nodes | Show the destructive part of the diff prominently, require explicit confirmation | Full undo retained | "This change removes the Fraud Check step you configured. Continue?" |

## 15.2 Execution Runtime

| Scenario | Expected behavior | Error handling |
|---|---|---|
| Tool returns 401 mid-execution | Attempt token refresh once; if it fails, suspend execution and alert the connection owner rather than failing outright | Execution enters `blocked_credentials`, resumable after reconnection |
| Tool returns 429 | Exponential backoff with jitter within the step budget, then dead-letter | Retry count recorded in the trace |
| Model provider outage | Fail over to the configured fallback provider or model | If none configured, suspend and retry rather than losing the execution |
| Agent loops (same tool, same args, repeatedly) | Loop detection halts the execution | Trace flags the loop; surfaced as a fixable quality issue, not a generic error |
| Execution exceeds cost budget | Hard stop at the budget ceiling | Notify owner, mark `budget_exceeded`, offer resume with a raised limit |
| Step succeeds but a later step fails, after an irreversible external write | Execute the declared compensating action if one exists; otherwise stop and escalate to a human with the exact state | **This is the most important runtime edge case.** The trace must clearly show what actually happened in the external system |
| Duplicate webhook delivery | Idempotency key deduplication within a window | Second delivery returns the first execution's ID, no double-run |
| Trigger fires while the previous run is still going | Configurable concurrency policy per agent: allow, queue, or skip | Default: queue, since business processes are usually order-sensitive |
| Agent version is rolled back while executions are in flight | In-flight executions complete on their pinned version | New executions use the rolled-back version |
| Knowledge base is updated mid-execution | Execution uses the index snapshot as of its start | Trace records the knowledge version consulted |
| Worker process crashes mid-step | Durable engine resumes from the last checkpoint | Steps must be idempotent, which is a design requirement on every executor |
| Tenant hits quota during a run | In-flight executions finish; new ones are rejected | "Your workspace has reached its monthly execution limit." |

## 15.3 Human Approval

| Scenario | Expected behavior |
|---|---|
| Approver does not respond before timeout | Escalate per the configured chain; on final timeout, apply the builder's declared default (fail, reject, or proceed), which must be an explicit choice at design time and never an implicit one |
| Approver has left the organization | Deprovisioning triggers reassignment of their pending approvals to the role or a fallback |
| Approver clicks a stale link after the decision was made | Show the existing decision with attribution; never allow a double-decide |
| Approval role has zero members | Blocked at pre-deploy validation, not discovered at runtime |
| Approver lacks context to decide | "Request more information" path returns to the requester or triggers an agent step to gather data |
| Requester is also the only approver | Blocked by segregation-of-duties policy at validation time |
| Notification delivery fails (email bounce, Slack app removed) | Fallback channel plus in-app queue; delivery failure is itself an alertable event |

## 15.4 Knowledge

| Scenario | Expected behavior |
|---|---|
| Unsupported or corrupt file | Reject at upload with a specific reason, never a silent ingestion failure |
| Scanned image PDF with no text layer | OCR fallback, or an explicit "no extractable text" status |
| Very large document | Chunked async processing with progress; hard size cap communicated up front |
| Document deleted from the source system | Sync removes it from the index; agents must not cite deleted content |
| Retrieval returns nothing relevant | Agent must say it does not know, never fabricate. This is a first-class product behavior, not a prompt afterthought |
| Embedding model change | Full re-index required; must be a managed background migration, not a breaking change |
| Document contains PII that should not be retrievable | Ingestion-time PII detection plus per-document access control |
| Two documents contradict each other (old and new policy) | Retrieval surfaces both with dates; the agent must flag the conflict rather than pick silently |

## 15.5 Multi-tenancy and Platform

| Scenario | Expected behavior |
|---|---|
| Tenant deleted | Cascade purge across Postgres, vector store, object storage and traces, with a grace period and an exportable archive |
| A tenant's traffic degrades others | Per-tenant concurrency caps and queue fairness |
| Marketplace agent references a tool the installing tenant lacks | Install succeeds in a partially-configured state with a clear mapping checklist |
| A user is removed while owning critical agents | Ownership transfer flow enforced before deactivation completes |
| Clock and timezone handling for scheduled triggers | Schedules stored with an explicit timezone; DST transitions handled deterministically and documented |

---

# 16. QA and Testing Strategy

## 16.1 Testing by Layer

| Type | Scope | Approach | Notes specific to this product |
|---|---|---|---|
| **Unit** | Node executors, policy engine, spec validator, patch engine | Standard, target high coverage on the spec and policy modules | The spec validator and policy engine are where correctness matters most |
| **Functional** | Each feature against its acceptance criteria | Manual plus automated | Golden path (S25) is the primary regression suite |
| **API** | Every endpoint | Contract tests from an OpenAPI spec, plus negative tests | Include authz negative tests on every endpoint, not a sample |
| **UI** | Canvas, builder, monitoring, admin | Playwright end to end | The canvas is high risk: node manipulation, large graphs, live state streaming, undo, concurrent edit |
| **Integration** | Each connector and MCP server | Sandbox accounts where available; record/replay fixtures otherwise; scheduled live smoke tests against real sandboxes | Connector breakage from upstream API changes is a certainty, so scheduled live tests are not optional |
| **Durability** | Execution engine | Chaos testing: kill workers mid-step, restart, verify exactly-once semantics and correct resumption | Highest technical risk area, deserves dedicated test infrastructure |
| **AI quality** | NL to spec, patching, agent reasoning | Golden dataset of prompts with structural assertions plus LLM-as-judge; report pass rate over N runs, not pass/fail on one | See 16.2 |
| **MCP** | Client behavior | Mock servers for happy path, slow responses, malformed schemas, schema drift, and **injection attempts in tool descriptions** | The injection test is a security test disguised as an integration test |
| **Security** | Isolation, authz, injection | Automated cross-tenant matrix in CI, authz fuzzing, dependency scanning, plus periodic external penetration testing and an AI red-team exercise | See 16.3 |
| **Performance** | Runtime and UI | Load test concurrent executions; canvas with 100+ nodes; trace ingestion throughput; retrieval latency at scale | Define SLOs before testing, not after |
| **Cross-browser / device** | Web app | Chrome, Edge, Safari, Firefox; the canvas realistically needs a desktop viewport | Approval views must work well on mobile, since approvers are frequently mobile |
| **Regression** | Everything above | Automated suite gating every release, plus a nightly AI-quality benchmark | AI quality regresses silently on model updates; only continuous measurement catches it |
| **UAT** | Business users on real processes | Design-partner-led, measuring time-to-first-working-agent | The real acceptance criterion is Section 30: can they do it without engineering help |

## 16.2 Testing Non-Deterministic AI (the hard part)

Conventional pass/fail testing does not work here. The recommended approach:

1. **Structural assertions rather than exact matching.** For NL-to-spec, assert that the graph contains an approval node before the write node, that all referenced tools exist, that the graph is acyclic and reachable. Do not assert an exact node list.
2. **Statistical pass rates with thresholds.** Run each golden case N times; require, for example, 90% structural validity and 80% semantic correctness. Alert on regression against the previous baseline.
3. **Tiered golden dataset:** 20 to 30 canonical business requests spanning departments, plus ambiguous requests, plus adversarial requests, plus requests referencing unavailable tools.
4. **LLM-as-judge with human calibration.** Judge prompts versioned and periodically re-validated against human labels, since an unmonitored judge drifts.
5. **Pinned model versions in CI**, with an explicit re-baselining process when the model is upgraded. Model upgrades must be treated as releases.
6. **Latency and cost as test assertions**, not just correctness. A correct generation that takes 90 seconds fails the product requirement.

## 16.3 High-Risk Areas Requiring Extra Testing

Ranked by severity of failure:

1. **Cross-tenant data isolation.** A single leak is potentially company-ending. Requires automated, continuous, adversarial testing across every access path including retrieval and traces.
2. **Credential handling.** Leakage into logs, traces, LLM context or error messages. Requires automated secret-scanning of all outbound payloads and stored artifacts.
3. **Prompt injection to unauthorized action.** Dedicated red-team suite with poisoned documents, poisoned tool outputs and poisoned MCP descriptions.
4. **Approval integrity.** Forged, replayed, bypassed or double-executed approvals. Test the token model exhaustively.
5. **Execution durability and idempotency.** Duplicate side effects are directly visible to the customer as duplicate invoices or duplicate employee records.
6. **Irreversible external actions.** Every write path needs an explicit test of the partial-failure case.
7. **Permission enforcement at the tool layer.** Verify that UI-hidden actions are also API-blocked and runtime-blocked.
8. **Cost accounting accuracy.** Billing disputes destroy trust; reconcile metered usage against provider invoices continuously.

---

# 17. MVP Definition

## 17.1 A contradiction that must be resolved first

**[GAP]** Section 25 says "We should NOT attempt to prototype every possible feature", and defines a single golden path. Section 26 then lists a "first release" spanning creation, configuration (models, tools, MCP, knowledge, memory, output, guardrails, approval), testing with datasets, staging and production deploys with rollback, full monitoring, RBAC, tenant isolation and audit. **[ASSUMPTION]** Section 25 describes a prototype and Section 26 describes a commercial GA release; they are two different milestones with, realistically, several quarters between them. This document treats them accordingly.

## 17.2 The MVP thesis

**The MVP must prove the riskiest assumption, not demonstrate the most features.** The riskiest assumption is A1: that a business user can describe a process in natural language and end up with a deployed, trusted, working agent. Everything that does not serve that proof is deferred.

**MVP success metric [RECOMMENDED]:** a business user at a design-partner company, without engineering help, creates and deploys an agent that runs successfully against their real systems, within one working session. This is Section 30 made measurable.

## 17.3 MVP Scope

**Domain constraint [RECOMMENDED]:** pick **one** department (HR onboarding is already the vision's chosen scenario) and one design partner. Breadth across Finance, HR, Sales, Support, IT and Legal at MVP guarantees shallow quality everywhere.

| Included in MVP | Why it must be here |
|---|---|
| NL agent generation into a validated spec | The core hypothesis, cannot be deferred |
| Visual canvas: view, edit config, insert, delete, reconnect nodes | "See and edit" is half the core promise |
| Conversational editing with a visible diff | The interaction model that distinguishes this from a canvas tool |
| Node types: Trigger (manual + schedule), AI Agent, Knowledge, Condition, Tool, Human Approval, Notification | The exact set the S25 golden path requires |
| 3 to 5 templates in the chosen domain | Reduces the burden on generation quality and shortens time-to-value |
| Knowledge base: upload, ingest, retrieve, cite | Pillar 4, required by the golden path |
| Connections: 2 to 3 real connectors (chosen by the design partner) + generic HTTP + MCP client | Proves integration without an unbounded build |
| Human approval with approver, role, timeout, escalation, rejection path, audit | Explicitly and unusually specified in S15, and the enterprise differentiator |
| Dry-run / simulated execution | Without it, users cannot test safely, so activation fails |
| Live execution on the canvas | S13 calls this an important part of the experience |
| Full execution trace covering the S16 questions | Trust is a core feature, and retrofitting traces is expensive |
| Versioning, deploy, rollback, two environments | S26, and required to make deployment feel safe |
| Cost and latency per execution | S9 shows it explicitly, and metering must be correct from the start |
| RBAC with 4 system roles (Admin, Builder, Approver, Viewer) | Minimum viable governance |
| Hard tenant isolation | Non-negotiable, architectural, not a feature |
| Immutable audit log | Same reasoning |
| Basic monitoring dashboard | Operating a deployed agent requires it |

## 17.4 Explicitly excluded from MVP, with rationale

| Excluded | Rationale |
|---|---|
| Marketplace | Zero value with one design partner; needs a portability model that does not exist yet (S18/S19 are Phase 3) |
| Multi-agent orchestration | The vision itself says "eventually" (S6); single-agent quality must come first |
| Memory | Undefined in the vision; cannot be built responsibly until scoped |
| Evaluation framework | Real, but manual testing suffices to prove the MVP thesis; needs proper design |
| Custom roles, SSO, SCIM | Needed to sell, not needed to validate. Design partners can use email login |
| Advanced guardrails | Basic PII redaction only in MVP |
| Broad connector library | Deliberately bounded; the generic HTTP and MCP escape hatches cover the gaps |
| Public API and SDK | No external consumers yet |
| Billing and metering-to-invoice | Metering yes, invoicing no |
| WhatsApp, mobile app, embedded widget | Surface expansion before core validation |

## 17.5 Phase 2 (make it sellable)

Theme: **from "it works for one partner" to "we can sell it to enterprises."**

- Evaluation framework with test datasets, scoring and deploy gating (closes the S10 lifecycle)
- Memory, once defined
- Guardrails configuration: PII, blocked topics, output constraints
- SSO (SAML/OIDC) and SCIM provisioning
- Custom roles and granular permission grants
- Webhook and connector-event triggers (the S25 "Employee Created" trigger)
- 10 to 15 additional connectors driven by real pipeline demand
- Alerting, error queue, bulk retry, debugging with step re-run
- Cost budgets and spend controls
- AI failure triage and improvement recommendations (AI-11, AI-12)
- Audit export and SIEM streaming
- Usage metering to billing
- Data retention controls and GDPR tooling
- Knowledge auto-sync from document sources
- SOC 2 readiness work

**Why here:** every item above is either a blocker raised by enterprise procurement and security reviews, or a requirement for operating more than a handful of agents. None of them is needed to prove the product concept.

## 17.6 Phase 3 (make it a platform)

Theme: **from "a product enterprises buy" to "an ecosystem and an operating layer."**

- Marketplace: listings, install with configuration contract, updates, and eventually third-party publishing with certification
- Multi-agent orchestration (manager and specialist agents, S6, S27)
- Platform as MCP server, plus a public API and SDK
- Advanced governance: policy-as-code, approval matrices, freeze windows
- Data residency and VPC or self-hosted runtime for regulated customers
- Model routing and cost optimization with evaluation evidence
- Agent-to-agent collaboration and the "agent workforce" view (S27)
- Advanced analytics: business-outcome measurement, not just system metrics
- Anomaly detection on agent behavior

**Why here:** each depends on a mature core. The marketplace in particular needs many working agents, a proven portability model and a certification process before it creates value rather than support burden.

---

# 18. Gaps and Questions

Grouped by who must answer them. Priority: **P0** blocks architecture or MVP scope, **P1** blocks Phase 2 planning, **P2** can wait.

## 18.1 Product and Commercial

| # | Question | Priority | Why it matters |
|---|---|---|---|
| 1 | Who is the primary user: business analyst, AI CoE team, or developer? | **P0** | Determines the entire UX, the sales motion and how much technical surface is exposed (S3 vs S26 contradiction) |
| 2 | Who is the economic buyer, and what is the pricing metric (per agent, per execution, per seat, consumption)? | **P0** | Determines what must be metered from day one, and the whole cost architecture |
| 3 | What is the target customer size and industry? | **P0** | Mid-market versus Fortune 500 changes security, deployment model and integration priorities completely |
| 4 | Which single department do we win first? | **P0** | Breadth at MVP means shallow quality across the board |
| 5 | Is there a committed design partner with real systems and a real process? | **P0** | Without one, MVP validation is theatre |
| 6 | Is the marketplace first-party only, or open to third parties? | P1 | Changes security model, review pipeline and liability |
| 7 | What is the definition of "success" numerically (time to first agent, agents per customer, execution volume)? | P1 | S30 is qualitative; the team needs a measurable target |
| 8 | Build versus buy for the durable execution engine? | **P0** | Weeks of difference and a hard-to-reverse decision |

## 18.2 Functional Definition

| # | Question | Priority |
|---|---|---|
| 9 | **What exactly is "Memory"?** Conversation, execution scratchpad, cross-execution entity memory, or semantic memory? | **P0** (it is in the S4 core diagram and the S26 first release) |
| 10 | What does "Evaluate" mean concretely? Who defines pass criteria, and does a failing evaluation block deployment? | **P0** |
| 11 | What are "Guardrails" specifically? | P1 |
| 12 | What is the complete trigger taxonomy for v1 (manual, schedule, webhook, connector event, email, chat, API)? | **P0** |
| 13 | **How does an end user actually interact with a deployed agent?** Portal, chat, embedded widget, or API only? | **P0** (entirely absent from the vision, and it is the whole product for support and helpdesk use cases) |
| 14 | Whose credentials does an agent use at runtime: workspace service account, builder's delegated token, or invoking user's token? | **P0** |
| 15 | What is a "Workspace": department, team, project, or environment? | **P0** |
| 16 | Do we support code escape hatches (custom function nodes)? | P1 (powerful, but a large security and sandboxing commitment) |
| 17 | How much can a user edit a generated agent's underlying prompts? | P1 |
| 18 | Is there a concept of an agent calling another agent in v1? | P2 |

## 18.3 Technical and Security

| # | Question | Priority |
|---|---|---|
| 19 | Cloud-only, or must we support VPC / on-premise deployment? | **P0** (fundamental architectural fork) |
| 20 | How do we reach systems behind a customer firewall (ERP, internal databases)? | **P0** (a gateway component is likely required and is not in scope anywhere) |
| 21 | Which model providers, and can customers bring their own keys or require a specific region? | **P0** |
| 22 | What are the data-residency requirements of the target market? | P1 |
| 23 | Is shared-infrastructure multi-tenancy acceptable to target customers? | **P0** |
| 24 | What is the target scale for planning (tenants, agents, concurrent executions, executions per day)? | P1 |
| 25 | What compliance certifications are required, and by when (SOC 2, ISO 27001, GDPR, HIPAA)? | P1 |
| 26 | What retention period applies to traces containing business data? | P1 |
| 27 | What are the availability and latency SLOs we will commit to? | P1 |

## 18.4 Contradictions to Resolve

| # | Contradiction | Where |
|---|---|---|
| C1 | User "should not need to understand MCP" versus "Configure MCP" in the first release | S3 versus S26 |
| C2 | "Do not prototype every feature" versus a first release listing roughly six major product areas | S25 versus S26 |
| C3 | Section 16 requires recording "what data was sent" versus data-minimisation and GDPR obligations for PII | S16 versus privacy law |
| C4 | Strict tenant isolation versus a marketplace that shares agent artifacts across tenants | S20 versus S18 |
| C5 | "Deterministic workflows" from workflow platforms versus autonomous agent reasoning | S23 versus S6 (the boundary must be explicitly designed, not assumed) |

---

# 19. Risks

Ordered by expected impact. Each has a concrete mitigation, not a platitude.

## 19.1 Business Risks

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| **Positioning collapse: "platform for everything" appeals to no one** | High | High | Choose one department and one wedge use case for MVP. Expand only after repeatable wins |
| **Heavily contested market** (Microsoft Copilot Studio, Salesforce Agentforce, ServiceNow, n8n, Zapier, LangGraph Platform, and vertical AI startups) | High | Certain | Differentiate on the operating layer (governance, trace, approval, evaluation), which incumbents bolt on late, and on being system-of-record agnostic, which the suite vendors structurally cannot be |
| **Long enterprise sales cycles exhaust runway before revenue** | High | Medium | Design for a self-serve, low-risk entry point (read-only agents, no write actions, minimal security surface) that lands before procurement |
| **Marketplace cold start** | Medium | High | Treat the marketplace as first-party curated content for a long time. Do not depend on ecosystem contribution |
| **Buyer is unidentified, so the product is built for nobody** | High | Medium | Question 1 and 2 in Section 18 must be answered before UX design |

## 19.2 Technical Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **NL-to-agent quality is not good enough to be trustworthy** | Critical, it is the core promise | Curated pattern library over raw generation, constrained schema generation, repair loop, clarifying questions, and always treat generation as a starting draft under human review. Measure quality continuously from week one |
| **Durable execution built incorrectly, forcing a rewrite** | Critical | Decide build-versus-buy immediately; prototype the suspend/resume/approval path in week one rather than last |
| **Integration long tail becomes an unbounded engineering commitment** | High | Three-tier connector strategy (MCP first, few curated connectors, generic escape hatches) |
| **Systems behind firewalls are unreachable** | High | Scope a gateway component early, or explicitly restrict the initial target market to cloud-native systems |
| **Trace data volume and cost explosion** | Medium | Partitioned storage, sampling for non-critical spans, tiered retention, and cost modelled before launch |
| **Model provider changes break behavior silently** | Medium | Pin versions, run nightly regression benchmarks, maintain a provider abstraction with fallback |

## 19.3 UX Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **The magic-then-cliff problem: generation delights, then twelve configuration blockers appear** | High | Visible TODO checklist on the canvas, guided resolution, mockable tools so a test run is possible before any real integration |
| **Canvas complexity creep re-creates the "configure 25 settings" experience S11 rejects** | High | Progressive disclosure: business view by default, advanced panel behind an explicit toggle for the Technical Steward persona |
| **Users cannot predict what the agent will do** (the determinism boundary) | High | Make the deterministic parts (workflow structure, conditions, approvals) visually distinct from the non-deterministic parts (agent reasoning), so users know where variability lives |
| **Approval fatigue leads to rubber-stamping** | Medium | Show consequences not payloads, batch similar approvals, and surface "this approval is always approved" as a candidate for removal |

## 19.4 Security Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Cross-tenant data leakage** | Company-ending | RLS at the data layer, per-tenant vector namespaces and keys, continuous automated isolation testing in CI |
| **Prompt injection causing unauthorized real-world actions** | Critical | Policy engine outside the model, untrusted-content isolation, approval gates on irreversible actions, execution budgets, red-team suite |
| **Credential compromise across many tenants** | Critical | Per-tenant encryption keys, vault storage, no secrets in logs or traces or model context, automated secret scanning, rotation support |
| **Privilege escalation via agents** | High | Effective-permission ceiling bounded by the invoking user, action-level grants, segregation of duties |
| **Malicious or compromised MCP server** | High | Admin approval before use, schema pinning with drift alerts, treating tool descriptions as untrusted, egress allowlisting |

## 19.5 Integration Risks

| Risk | Mitigation |
|---|---|
| Upstream API changes break production agents | Scheduled live smoke tests per connector, schema-drift detection, and a fast connector release path independent of platform releases |
| Irreversible actions on partial failure | Side-effect classification per tool, compensating actions, human escalation with exact state, and dry-run everywhere |
| OAuth token expiry causing silent production failure | Proactive expiry monitoring, pre-emptive alerts, deploy-time credential validation |
| Rate limits on customer systems | Per-connection throttling configured by the admin, backoff, and queue-based smoothing |

## 19.6 AI Risks

| Risk | Mitigation |
|---|---|
| Hallucinated tools, fields or outputs | Constrained generation, schema validation on every boundary, capability-restricted catalogs |
| Non-determinism eroding trust | Test sets over single runs, pinned models, temperature control, evaluation gates before deploy |
| Cost runaway from loops or long contexts | Per-execution and per-tenant hard budgets, loop detection, context size limits |
| Agent confidently wrong on financial or HR data | Field-level confidence, thresholded human escalation, mandatory approval on high-impact writes, citations on knowledge-derived claims |
| Regulatory exposure from automated decisions affecting individuals | Human-in-the-loop for consequential decisions, full decision traces, and explainability per step (this is also an EU AI Act consideration worth legal review) |

## 19.7 Scalability Risks

| Risk | Mitigation |
|---|---|
| Noisy-neighbor contention | Per-tenant concurrency caps, queue fairness, isolated worker pools for large tenants |
| Execution and trace tables outgrowing the primary database | Time-based partitioning from day one, archival tiering, and separating the trace store if volume demands it |
| Vector index growth and re-index cost | Namespace-per-tenant, incremental indexing, and planning the embedding-migration path before the first model change |
| Canvas performance on large agents | Virtualized rendering, and a soft node-count guidance limit in the builder |

---

# 20. Recommended Next Steps

Durations are **[ASSUMPTION]** based on a team of roughly 6 to 8 people (1 PM, 1 designer, 3 to 4 engineers including one with AI/ML depth, 1 QA, part-time DevOps and security). Adjust to actual staffing.

### Step 1: Requirements clarification (1 to 2 weeks)
Answer every **P0** question in Section 18. Secure a named design partner with a real process, real systems and a real user willing to be observed. Resolve the five contradictions. **Exit criteria:** a signed-off decision log covering primary user, pricing metric, deployment model, memory definition, evaluation definition, runtime identity model and trigger taxonomy. Nothing downstream is safe to start without these.

### Step 2: Product flows and scope lock (1 to 2 weeks)
Write the golden path as a fully specified user story with acceptance criteria. Produce role and permission matrices. Define the agent lifecycle state machine explicitly. Lock MVP scope in writing. **Exit criteria:** approved MVP scope document, prioritized backlog, and the MVP success metric agreed numerically.

### Step 3: Architecture and technical spikes (2 to 3 weeks, partly parallel with Step 2)
Three spikes, run in parallel because each can invalidate the plan:
- **Spike A: NL-to-spec quality.** Build a throwaway generator against a draft spec schema and 20 test prompts. Measure structural validity and semantic correctness. This directly tests assumption A1, the riskiest thing in the vision.
- **Spike B: Durable execution.** Prototype an execution that suspends for a human approval, survives a worker restart, times out, escalates and resumes. Decide build versus buy on the evidence.
- **Spike C: Tenant isolation.** Prove RLS plus vector namespacing plus credential encryption end to end, with an automated cross-tenant test suite.

**Exit criteria:** an architecture decision record set, the five foundational decisions from Section 11.1 committed, and a go/no-go on the NL generation approach.

### Step 4: Data model and API design (1 to 2 weeks)
Finalize the **Agent Spec JSON schema first**, since everything depends on it. Then the relational schema with RLS policies, then the OpenAPI contract. Version the spec schema from v1 with a migration strategy, because agent specs will need to evolve and existing versions must remain executable.

### Step 5: UI/UX design (2 to 4 weeks, overlapping development)
Priority order: the generation-to-canvas moment, the TODO-resolution pattern, the live execution view, the trace view, and the approval view (including its mobile and out-of-app forms). **[RECOMMENDED]** Prototype and user-test the generation-to-canvas moment with real business users before building it, because if that moment does not land, no amount of engineering rescues the product.

### Step 6: Development (8 to 12 weeks for MVP)
Sequenced so that risk is retired early and there is always a demoable path:
1. Foundation: tenancy, auth, RBAC, spec schema, audit
2. Execution engine plus three node types (trigger, tool, notification), end to end
3. Human approval, suspend and resume, timeout and escalation
4. Knowledge ingestion and retrieval
5. Canvas: render, edit, validate
6. NL generation and conversational patching
7. Trace capture and the trace UI
8. Versioning, deploy, rollback
9. Monitoring, cost and dashboard

Build a working vertical slice by the end of item 2, then widen. Avoid building all of the UI before any of the runtime, which is the most common failure pattern in platform products of this shape.

### Step 7: Integrations (parallel from week 4)
MCP client layer first, since it is the tool interface for everything else. Then the generic HTTP connector, then the design partner's two or three specific systems. Build the connector test harness alongside, not after.

### Step 8: QA (continuous, with a hardening period of 2 to 3 weeks)
Automate the golden path and the isolation suite from the first sprint. Stand up the AI quality benchmark early enough to have a baseline. Reserve dedicated time for the chaos and durability testing and for the security red-team exercise.

### Step 9: UAT with the design partner (2 to 3 weeks)
The real test is Section 30: can a business user complete the full journey without engineering help? Measure time to first working agent, count every point where they needed help, and treat each of those points as a P1 defect rather than a training issue.

### Step 10: Production launch (2 weeks)
Runbooks, on-call, SLOs, alerting, backup and restore verification, incident process, a documented rollback plan, support tooling, and a security review sign-off. Launch to a small number of controlled customers with feature flags, not a general release.

### Recommended parallel tracks
- **Security and compliance:** start SOC 2 gap analysis during Step 6, not after launch
- **Design partner engagement:** continuous, not just at UAT
- **AI quality measurement:** from Step 3 onward, as a permanent instrument rather than a one-off test

---
---

# FINAL OUTPUT

## A. One-Paragraph Understanding of the Product

An enterprise, multi-tenant SaaS platform that lets a non-engineer describe a business process in natural language and receive a working AI agent: the platform's design AI generates a visual, editable workflow of typed nodes (trigger, reasoning, knowledge retrieval, condition, tool call, human approval, notification), the user refines it conversationally or on a canvas, connects it to enterprise systems and company knowledge, tests it safely, and deploys a versioned agent that runs in production under enterprise governance. The differentiator is not the builder but the operating layer beneath it: every execution is durable enough to pause for days awaiting human approval, fully traced (what was asked, decided, retrieved, called, sent, approved, and what it cost), permissioned at six levels from user down to individual action, strictly isolated per tenant, versioned and rollback-able. In one sentence, borrowed from the vision itself: this is not a canvas where users wire AI nodes together, it is a platform for turning business intent into trustworthy production AI agents, and the long-term ambition is a marketplace of installable business capabilities and an agent workforce operating alongside human employees.

## B. Feature Inventory (condensed)

| Pillar | MVP | Phase 2 | Phase 3 |
|---|---|---|---|
| **Create** | NL generation, canvas edit, conversational patching with diff, templates, validation | Advanced node types, code escape hatch (if approved) | Multi-agent composition |
| **Intelligence** | Reasoning, tool selection, retrieval, structured output, escalation, failure handling, long-running | Memory, guardrails, confidence-based escalation | Model routing, optimization |
| **Connect** | MCP client, generic HTTP, 2 to 3 curated connectors, OAuth, action-level scoping | 10 to 15 connectors, event triggers, on-prem gateway | Platform as MCP server, public SDK |
| **Knowledge** | KB CRUD, ingestion pipeline, retrieval, citations, access control | Live source sync, retrieval playground, permission mirroring | Advanced hybrid retrieval |
| **Human-in-loop** | Approver/role, timeout, escalation, conditions, rejection path, audit, out-of-app approval | Delegation, segregation of duties, approval analytics | Approval matrices, policy-as-code |
| **Test/Evaluate** | Manual run, dry-run, live canvas, trace | Test datasets, eval framework, deploy gating, version comparison | Continuous production evaluation |
| **Deploy** | Versioning, staging + production, deploy, rollback, manual + schedule triggers | Webhook and event triggers, freeze windows | Blue/green, canary |
| **Operate** | Monitoring, cost, latency, execution list, trace UI | Alerting, error queue, bulk retry, debugging, AI triage | Anomaly detection, business-outcome analytics |
| **Govern** | RBAC (4 roles), tenant isolation, action permissions, audit log | SSO, SCIM, custom roles, retention, GDPR tooling, SIEM export | Data residency, VPC deploy, certification |
| **Discover** | Templates only | Curated internal library | Full marketplace with install contracts and publishing |

## C. User Roles

Platform Super Admin (vendor) · Tenant Owner/Org Admin · Workspace Admin · Agent Builder/Author · Approver/Business Reviewer · Agent Operator/SRE · Auditor/Compliance · Technical Steward/Integration Engineer · End Consumer · Marketplace Publisher (Phase 3). Full capability, restriction, data-access and permission matrix in Section 3. All roles are **[RECOMMENDED]**; the vision defines none.

## D. Major User Flows

1. **Business Author creates and deploys an agent** (the golden path, Section 4.1)
2. **Approver decides a runtime human task** (Section 4.3)
3. **Workspace Admin connects an enterprise system** (Section 4.4)
4. **Operator investigates and remediates a production failure** (Section 4.5)
5. **End Consumer uses a deployed agent** (Section 4.6) - **[GAP]** the surface for this is undefined in the vision
6. **Install from marketplace** (Section 4.7, Phase 3)

## E. Admin Capabilities

Two distinct surfaces. **Customer admin:** org dashboard, users and roles, workspaces, connections and credentials, knowledge management, agent registry, deployment governance, policy configuration, audit log, cost and usage, notifications, error management, security settings, data controls. **Vendor admin [RECOMMENDED, absent from the vision]:** tenant lifecycle, fleet health, model provider operations, audited support impersonation, feature flags, billing operations, abuse and safety, marketplace review. Detail in Section 5.

## F. Client Capabilities

Create, Configure, Connect, Know, Test, Evaluate, Deploy, Operate, Govern, Consume. Full enumeration in Section 6.

## G. AI Opportunities

Fifteen identified across three distinct roles. **AI as Designer:** NL-to-spec generation (core), conversational graph patching (core), requirement clarification, schema mapping autofill, test case generation. **AI as Worker:** reasoning and tool selection (core), retrieval and query rewriting (core), document extraction (core for the named use cases), guardrail classifiers, confidence-based escalation. **AI as Operator's Assistant [largely absent from the vision and a strong differentiator]:** failure triage and root-cause summarization, improvement recommendations from production traces, cost and model optimization, evaluation judging, marketplace matching. Detail, inputs, outputs, approaches and risks in Section 7.

## H. MCP Opportunities

Three roles. **(1) Platform as MCP client [stated]:** make MCP the platform's single internal tool interface so every MCP server becomes a supported integration and all first-party connectors are wrapped as internal MCP servers, giving one invocation path, one policy enforcement point and one trace format. **(2) Platform as MCP server [recommended, not in the vision]:** expose `invoke_agent`, `search_knowledge`, `list_pending_approvals` and similar so external AI clients can use the platform, which inverts the integration burden and partly answers the missing end-consumer surface. **(3) Internal engineering MCP (Jira, GitHub, Slack, Drive, Sentry):** productivity for the build team, explicitly not a product feature. Custom servers worth building: an Internal Tool Gateway MCP deployed inside customer networks (which solves the firewall reachability gap), a Knowledge MCP, and an Approval MCP. Principal risks: tool-description injection, schema drift, authorization granularity, unvetted third-party servers. Detail in Section 10.

## I. Integration Requirements

Strategy: three tiers (MCP-first, a handful of curated first-party connectors, generic HTTP/SQL/webhook escape hatches) rather than N bespoke integrations. Register of 17 integration categories with rationale, APIs, auth methods, data exchanged, triggers and risks in Section 9. Highest-risk items: ERP (frequently not internet-reachable), HRIS (Workday complexity and PII), direct database access (security exposure), and customer-supplied MCP servers (injection and drift). Cross-cutting risks: firewall reachability, non-transactional write actions, permission fidelity, and absent vendor sandboxes.

## J. Recommended Architecture

Modular monolith split into a synchronous **control plane** and an asynchronous **data plane**, over PostgreSQL with row-level security, pgvector, object storage, Redis and a KMS-backed secret vault. React plus a mature graph library for the canvas, with SSE/WebSocket for live execution state. A provider-abstracted model router. An MCP-based tool invocation layer behind a deterministic policy decision point. A durable execution engine with per-step checkpointing. Structured execution traces as first-class product data, separate from system telemetry. Five foundational decisions that determine whether the prototype survives to production: (1) the Agent Spec is the single source of truth for design, canvas, runtime, versioning, marketplace and evaluation, (2) durable execution from day one, (3) a policy decision point between the model and every tool call, (4) tenant isolation at the data layer rather than in application code, (5) traces as data, not logs. Full detail and deliberate technology exclusions in Section 11.

## K. MVP Scope

One department, one design partner, one golden path. NL generation into a validated spec; canvas view and edit; conversational editing with a visible diff; seven node types; 3 to 5 templates; knowledge base with ingestion, retrieval and citations; MCP client plus generic HTTP plus 2 to 3 real connectors; human approval with the full Section 15 feature set; dry-run execution; live canvas execution; complete execution traces; versioning with staging, production and rollback; cost and latency metering; four RBAC roles; hard tenant isolation; immutable audit log; a basic monitoring dashboard. Explicitly excluded: marketplace, multi-agent, memory, evaluation framework, SSO/SCIM, broad connectors, public API, billing. **Success metric:** a business user at the design partner creates and deploys a working agent against their real systems, in one session, without engineering help. Rationale per item in Section 17.

## L. Phase 2 and Phase 3

**Phase 2 (make it sellable):** evaluation framework with deploy gating, memory, guardrails, SSO and SCIM, custom roles, webhook and event triggers, 10 to 15 connectors, alerting and error management, cost budgets, AI failure triage and improvement suggestions, audit export, usage-to-billing, retention and GDPR tooling, knowledge auto-sync, SOC 2 readiness. Everything here is either an enterprise procurement blocker or an operational necessity at scale, and none of it is needed to validate the concept.

**Phase 3 (make it a platform):** marketplace with install contracts and third-party publishing, multi-agent orchestration, platform-as-MCP-server plus public API and SDK, policy-as-code governance, data residency and VPC or self-hosted runtime, model routing with evaluation-backed cost optimization, agent-to-agent collaboration and the agent workforce view, business-outcome analytics, behavioral anomaly detection. Each depends on a mature core.

## M. Risks

**Highest severity, in order:** cross-tenant data leakage (company-ending; mitigate with data-layer isolation and continuous automated adversarial testing) · prompt injection causing unauthorized real-world actions (mitigate with a policy engine outside the model, untrusted-content isolation, approval gates on irreversible actions) · NL-to-agent quality falling short of trustworthy (mitigate with a curated pattern library, constrained generation, repair loops, and human review as a required step) · durable execution built wrong, forcing the rewrite Section 21 forbids (mitigate by spiking it in week one and deciding build-versus-buy on evidence) · positioning collapse from targeting every department at once (mitigate by choosing one wedge) · the magic-then-cliff UX problem (mitigate with visible TODO resolution and mockable tools) · the unbounded integration long tail (mitigate with the three-tier connector strategy) · irreversible actions on partial failure (mitigate with side-effect classification and compensating actions). Full register across business, technical, UX, security, integration, AI and scalability risks in Section 19.

## N. Open Questions

**P0, blocking architecture or MVP scope:** Who is the primary user (the S3-versus-S26 contradiction)? Who is the buyer and what is the pricing metric? What is the target customer size and segment? Which single department first? Is there a committed design partner? Build or buy the execution engine? What exactly is "Memory"? What does "Evaluate" mean and does it gate deployment? What is the trigger taxonomy for v1? **How does an end user actually interact with a deployed agent?** Whose credentials does an agent use at runtime? What is a "Workspace"? Cloud-only or VPC/on-premise? How do we reach systems behind a firewall? Which model providers, and can customers bring their own keys? Is shared-infrastructure multi-tenancy acceptable?

**Five contradictions requiring resolution:** MCP hidden from users versus MCP configurable in the first release; "do not prototype everything" versus a six-area first release; recording all data sent versus GDPR data minimisation; strict tenant isolation versus a cross-tenant marketplace; deterministic workflows versus autonomous agent reasoning. Full list with priorities in Section 18.

## O. Recommended Next Steps

1. **Requirements clarification** (1 to 2 wks): answer all P0 questions, resolve the contradictions, secure a design partner. Nothing downstream is safe without this.
2. **Product flows and scope lock** (1 to 2 wks): golden path with acceptance criteria, role matrix, lifecycle state machine, numeric success metric.
3. **Architecture and three parallel spikes** (2 to 3 wks): NL-to-spec quality, durable execution with approval suspend/resume, tenant isolation end to end. Each can invalidate the plan, so run them first.
4. **Data model and API design** (1 to 2 wks): Agent Spec schema first, then relational schema with RLS, then the OpenAPI contract.
5. **UI/UX** (2 to 4 wks, overlapping): user-test the generation-to-canvas moment with real business users before building it.
6. **Development** (8 to 12 wks): foundation, then a vertical execution slice, then approval, knowledge, canvas, generation, traces, deploy, monitoring. Never build all the UI before any of the runtime.
7. **Integrations** (parallel from wk 4): MCP layer, generic HTTP, then the partner's specific systems, with the connector test harness built alongside.
8. **QA** (continuous, plus 2 to 3 wks hardening): golden path and isolation suites automated from sprint one; AI quality baseline established early; dedicated chaos testing and security red-teaming.
9. **UAT** (2 to 3 wks): can a business user complete the journey unaided? Every point where they needed help is a P1 defect, not a training gap.
10. **Production launch** (2 wks): runbooks, SLOs, on-call, backup restore verification, security sign-off, controlled rollout behind feature flags.

**Parallel tracks throughout:** security and SOC 2 gap analysis from Step 6, continuous design-partner engagement, and permanent AI quality measurement from Step 3 onward.

---

## Closing Note on the Vision Itself

The vision document is unusually clear about what the product is *not* (Section 22) and unusually specific in two places that matter most commercially: human-in-the-loop requirements (Section 15) and trace completeness (Section 16). Those two sections read like they came from a real enterprise conversation, and they are the strongest signal in the document about where the product's actual value lies.

The weakest areas are the ones that determine feasibility rather than desirability: no defined user, no buyer, no pricing metric, no end-consumer surface, no definition of memory or evaluation, no deployment model, and no acknowledgement of the firewall-reachability problem. None of these is fatal, but all of them are cheaper to resolve now than after Step 6.

The single most valuable expansion opportunity beyond the current vision is **AI as the operator's assistant** (Section 7.3). The vision applies AI thoroughly to building agents and to being agents, but barely at all to operating them. Failure triage, improvement recommendations derived from production traces, and evaluation-backed cost optimization would close the Section 10 lifecycle loop that currently ends with an undefined "Improve" step, and they are exactly the capabilities that turn a build tool into an operating platform, which is what Section 29 says the product is meant to be.
