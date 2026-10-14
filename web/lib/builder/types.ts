/** Shapes of the builder API (apps/backend/builder). */

export type NodeType =
  | "input"
  | "manual_trigger"
  | "schedule_trigger"
  | "agent"
  | "tool"
  | "condition"
  | "join"
  | "human_approval"
  | "output";

export type Risk = "read" | "edit" | "delete";

export interface ApprovalPolicy {
  read: boolean;
  edit: boolean;
  delete: boolean;
}

export interface AgentConfig {
  llm?: { temperature?: number | null; max_output_tokens?: number | null; reasoning_effort?: string };
  tool_ids?: string[];
  knowledge_base_ids?: string[];
  response?: { tone?: string; verbosity?: string; language?: string; citations?: string; formats?: string[] };
  tools?: { max_calls?: number; timeout_seconds?: number; on_failure?: string };
  reliability?: { retries?: number; request_timeout_seconds?: number | null; fallback_model?: string; retry_on?: string[] };
  approvals?: ApprovalPolicy;
  guardrails?: GuardrailSettings;
  /** What a person sees on an empty chat: a welcome line and suggested first questions. */
  chat?: { welcome?: string; starters?: string[] };
  /** Long-term memory of each person it works for. */
  memory?: { enabled?: boolean; max_items?: number };
  /** Other standalone agents it may hand tasks to (each becomes an "ask_<name>" tool). */
  sub_agent_ids?: string[];
  [key: string]: unknown;
}

/** Safety checks around every run of an agent (all off by default). */
export interface GuardrailSettings {
  injection?: boolean;
  tool_injection?: boolean;
  pii_input?: boolean;
  pii_output?: boolean;
  groundedness?: boolean;
  groundedness_mode?: "fast" | "llm";
  groundedness_min?: number;
  custom_rules?: string[];
  on_violation?: "flag" | "block";
}

/** Something a guardrail found or did during a run. */
export interface GuardrailFlag {
  rule: string;
  severity: "low" | "medium" | "high";
  message: string;
  node_id?: string;
}

export interface DraftAgent {
  name: string;
  role: string;
  goal: string;
  instructions?: string;
  llm_provider?: string;
  llm_model?: string;
  config: AgentConfig;
}

export interface Agent extends DraftAgent {
  id: string;
  instructions: string;
  llm_provider: string;
  llm_model: string;
  workflow_id: string | null;
  owner_id: string;
  version: number;
  can_manage: boolean;
  created_at: string;
  updated_at: string;
}

/** Something an agent remembers about the signed-in person. */
export interface AgentMemory {
  id: string;
  content: string;
  /** The run where the agent saved it; null when the person added it. */
  source_run_id: string | null;
  created_at: string;
}

export interface UsageDay {
  date: string;
  runs: number;
  succeeded: number;
  failed: number;
  tokens: number;
  cost_usd: number;
}

/** Runs, tokens and estimated cost of an agent or workflow over a window. */
export interface Usage {
  /** "everyone" for its manager (numbers only), else "mine". */
  scope: "everyone" | "mine";
  days: number;
  runs: number;
  succeeded: number;
  failed: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  unpriced_runs: number;
  avg_cost_usd: number | null;
  avg_seconds: number | null;
  by_purpose: Record<string, number>;
  daily: UsageDay[];
}

/** A file sent with a chat message. */
export interface Attachment {
  id: string;
  filename: string;
  kind: "document" | "image";
  size: number;
  chars: number;
}

export interface Webhook {
  id: string;
  agent_id: string;
  name: string;
  token_prefix: string;
  instruction: string;
  enabled: boolean;
  requests_per_minute: number;
  last_used_at: string | null;
  last_run_id: string | null;
  created_at: string;
}

export interface WebhookCreated extends Webhook {
  /** The URL with its secret token — shown once. */
  url: string;
}

/** A server an agent's tools (or its team's) live on, and whether you've connected it. */
export interface AgentRequirement {
  server_id: string;
  name: string;
  connected: boolean;
  tools: string[];
}

export interface AgentRequirements {
  requirements: AgentRequirement[];
  ready: boolean;
}

/** An agent exported as a file (tools by server and tool name, not by id). */
export interface AgentFile {
  format: string;
  format_version: number;
  agent: { name: string; role: string; goal: string; instructions?: string; llm_provider?: string; llm_model?: string; config: AgentConfig };
  tools: { server: string; tool: string }[];
  knowledge_bases: string[];
  sub_agents: string[];
}

export interface InputVariable {
  name: string;
  label?: string | null;
  type?: "text" | "number" | "boolean" | "json";
  required?: boolean;
  description?: string | null;
}

export interface ConditionRule {
  field?: string;
  op: string;
  value?: string | number;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  position?: { x: number; y: number };
  label?: string | null;
  retry?: { max_attempts: number } | null;
  variables?: InputVariable[] | null;
  agent_id?: string | null;
  draft_agent?: DraftAgent | null;
  config_overrides?: Record<string, unknown> | null;
  tool_id?: string | null;
  need?: string | null;
  tool_args?: Record<string, unknown> | null;
  message_template?: string | null;
  condition_config?: {
    mode?: "ai" | "rule";
    instructions?: string | null;
    rules?: Record<string, ConditionRule>;
    default_branch?: string | null;
  } | null;
  join_policy?: { mode: "all" | "any" | "count"; min_required?: number | null } | null;
  approval_message?: string | null;
  output_config?: { format?: string; language?: string | null; header?: string; footer?: string; compose?: string } | null;
  /** schedule_trigger: when the workflow runs by itself. */
  schedule?: TriggerSchedule | null;
}

export interface TriggerSchedule {
  cron?: string;
  timezone?: string;
  enabled?: boolean;
  /** What each scheduled run is asked. */
  input?: string;
  variables?: Record<string, unknown>;
}

export interface Schedule {
  id: string;
  kind: "agent" | "workflow";
  agent_id: string | null;
  workflow_id: string | null;
  node_id: string | null;
  cron: string;
  timezone: string;
  description: string;
  input: { text?: string; variables?: Record<string, unknown> };
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_id: string | null;
  last_status: "started" | "skipped" | "error" | null;
  last_error: string | null;
  owner_id: string;
  is_mine: boolean;
  /** Agent schedules are changed directly; a workflow's on its Schedule step. */
  editable: boolean;
  created_at: string;
}

export interface Version {
  id: string;
  version: number;
  /** "Created", "Saved", "Restored from v3", "Before version history". */
  note: string;
  /** What changed since the version before, in words. */
  summary: string;
  author_id: string | null;
  author_name: string | null;
  created_at: string;
  is_current: boolean;
}

/** A version with its full definition (agent fields, or a workflow's graph + its own agents). */
export interface VersionDetail extends Version {
  snapshot: {
    name?: string;
    role?: string;
    goal?: string;
    instructions?: string;
    llm_provider?: string;
    llm_model?: string;
    description?: string;
    nodes?: WorkflowNode[];
    edges?: WorkflowEdge[];
    config?: Record<string, unknown>;
    agents?: Record<string, { name: string; role: string; goal: string; instructions?: string; config?: AgentConfig }>;
  };
}

export type TestCategory = "normal" | "ambiguous" | "knowledge_gap" | "tools" | "safety" | "injection" | "out_of_scope";

export interface TestCase {
  id: string;
  title: string;
  input: string;
  /** What a good response does (a behaviour, not exact wording). */
  expectation: string;
  category: TestCategory;
  variables: Record<string, unknown>;
  source: "manual" | "generated";
  created_at: string;
}

export interface TestResult {
  id: string;
  case_id: string | null;
  run_id: string | null;
  title: string;
  category: TestCategory;
  input: string;
  expectation: string;
  /** error = it couldn't run (or couldn't be judged). */
  status: "running" | "grading" | "passed" | "failed" | "error";
  score: number | null;
  reasoning: string | null;
  answer: string | null;
}

export interface TestRun {
  id: string;
  kind: "agent" | "workflow";
  definition_version: number;
  status: "running" | "done" | "cancelled";
  /** 0-100 */
  score: number | null;
  passed: number;
  total: number;
  done: number;
  dimensions: Partial<Record<"behaviour" | "knowledge" | "tools" | "safety", number>>;
  created_at: string;
  finished_at: string | null;
  results?: TestResult[] | null;
}

/** One line per agent/workflow for the Executions list (GET /builder/overview). */
export interface OverviewItem {
  kind: "agent" | "workflow";
  id: string;
  runs: number;
  succeeded: number;
  failed: number;
  /** Runs per day over the window, oldest first. */
  daily: number[];
  last_run_at: string | null;
  last_status: RunStatus | null;
  running: number;
  waiting: number;
  health_status: Health["status"];
  health_score: number | null;
  schedule: string | null;
  next_run_at: string | null;
  published: number;
}
export interface Overview {
  days: number;
  totals: { runs: number; succeeded: number; failed: number; running: number; waiting: number };
  items: OverviewItem[];
}

/** How ready an agent/workflow is (GET /builder/{agents|workflows}/{id}/health). */
export interface Health {
  /** 0–100 over the measured parts; null until something is measured. */
  score: number | null;
  status: "production_ready" | "testing" | "needs_attention" | "not_tested";
  runs_counted: number;
  dimensions: { key: string; label: string; weight: number; score: number | null; measured: boolean; summary: string; detail: string[] }[];
  blockers: { key: string; severity: "critical" | "warning"; title: string; detail: string; fix: string }[];
}

/** The signed-in user's runs for the dashboard (GET /builder/insights). */
export interface InsightsWindow {
  runs: number;
  succeeded: number;
  failed: number;
  success_rate: number;
  avg_latency_ms: number;
  /** Distinct agents/workflows that ran. */
  active: number;
}
export interface Insights {
  days: number;
  current: InsightsWindow;
  previous: InsightsWindow;
  /** Two windows of days, oldest first (UTC dates). */
  series: { date: string; succeeded: number; failed: number }[];
  busiest: { kind: "agent" | "workflow"; id: string; name: string; exists: boolean; runs: number; succeeded: number }[];
  all_time: { runs: number; success_rate: number };
}

/** Everything the signed-in user published, at a glance (GET /builder/published). */
export interface Published {
  days: number;
  stats: { live_keys: number; total_requests: number; success_rate: number; avg_latency_ms: number };
  /** One per day, oldest first (UTC dates). */
  series: { date: string; success: number; error: number }[];
  keys: (PublicKey & { kind: "agent" | "workflow"; target_id: string; target_name: string; requests: number })[];
}

export interface PublicKey {
  id: string;
  name: string;
  key_prefix: string;
  status: "active" | "paused" | "revoked";
  /** null = always the latest saved version. */
  version: number | null;
  allowed_origins: string[];
  requests_per_minute: number;
  daily_quota: number | null;
  runs_today: number;
  last_used_at: string | null;
  created_at: string;
  owner_id: string;
  is_mine: boolean;
}

/** Returned once, at creation: the key itself. */
export interface PublicKeyCreated extends PublicKey {
  key: string;
}

export interface PublishCheck {
  version: number;
  /** "Server.tool" a caller could make it use that change data. */
  write_tools: string[];
  /** Why it can't run right now (as you). */
  problems: string[];
  advice: string[];
}

export interface SchedulePreview {
  ok: boolean;
  error: string | null;
  description: string;
  next_runs: string[];
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string | null;
}

export type ApprovalOverride = "default" | "always" | "never";

export interface WorkflowConfig {
  /** null = no limit */
  max_run_seconds?: number | null;
  max_steps?: number;
  on_node_failure?: "abort" | "skip" | "retry";
  node_retry_count?: number;
  /** With on_node_failure "retry": once the retries are used up. */
  node_retry_fallback?: "abort" | "skip";
  include_step_summary?: boolean;
  default_knowledge_base_ids?: string[];
  /** This workflow's own knowledge base (Settings → Knowledge). */
  own_knowledge_base_id?: string | null;
  approvals?: ApprovalPolicy;
  approval_overrides?: { read?: ApprovalOverride; edit?: ApprovalOverride; delete?: ApprovalOverride };
}

export type AnswerDepth = "auto" | "short" | "detailed";

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  version: number;
  node_count: number;
  can_manage: boolean;
  created_at: string;
  updated_at: string;
}

export interface Workflow extends WorkflowSummary {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  config: WorkflowConfig;
  agents: Agent[];
}

export interface Problem {
  code: string;
  message: string;
  node_id?: string;
  edge_id?: string;
  server_id?: string;
}

export interface CheckResult {
  ok: boolean;
  problems: Problem[];
}

export interface ToolCandidate {
  tool_id: string;
  server_id: string;
  server_name: string;
  tool_name: string;
  description: string;
  risk: Risk;
  connected: boolean;
  /** Why the assistant picked it (agent drafts only). */
  reason?: string;
}

export interface ServerTools {
  server_id: string;
  server_name: string;
  connected: boolean;
  tools: { name: string; description: string; input_schema: Record<string, unknown> | null; risk: { risk: Risk } }[];
}

export interface Draft {
  problems: Problem[];
  needs_connection: { server_id: string; server_name: string }[];
  tools: Record<string, ToolCandidate[]>;
}

export interface WorkflowDraft extends Draft {
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  config: WorkflowConfig;
}

export interface AgentDraft extends Draft {
  name: string;
  role: string;
  goal: string;
  instructions: string;
  config: AgentConfig;
  insights: AgentInsights;
}

export type ProfileId = "quality" | "balanced" | "speed" | "cost";

/** Why an agent draft is set up the way it is (POST /assist/agent). */
export interface AgentInsights {
  /** The outside systems the assistant read the description as needing ("" = none). */
  needs: string;
  profile: ProfileId;
  profile_reason: string;
  knowledge: { recommended: boolean; reason: string };
  /** A realistic first request to test it with. */
  try_asking: string;
  /** Tools from the same search that weren't picked — optional extras. */
  related_tools: ToolCandidate[];
}

/** A one-click settings preset (GET /assist/agent-profiles). */
export interface AgentProfile {
  id: ProfileId;
  label: string;
  summary: string;
  config: AgentConfig;
}

export interface WorkflowEditResult {
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  config: WorkflowConfig;
  summary: string | null;
  answer: string | null;
  changes: string[];
  warnings: string[];
  problems: Problem[];
}

export type RunStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";

/** A playground chat with an agent or workflow; its runs are its messages. */
export interface Conversation {
  id: string;
  kind: "agent" | "workflow";
  agent_id: string | null;
  workflow_id: string | null;
  title: string;
  turn_count: number;
  created_at: string;
  last_message_at: string | null;
}

/** Continue a chat, or start one with this message (omit both for a one-off run). */
export interface ChatRef {
  conversation_id?: string | null;
  new_conversation?: boolean;
}

export interface Approval {
  id: string;
  run_id: string;
  kind: "tool_call" | "uncertain_call" | "human_step" | "missing_input";
  node_id: string | null;
  tool_name: string | null;
  risk: Risk | null;
  status: string;
  payload: {
    message?: string;
    arguments?: Record<string, unknown>;
    server_name?: string;
    tool_name?: string;
    text?: string;
    missing?: string[];
    errors?: string[];
    requester?: string;
    step?: string;
  };
  created_at: string;
}

export interface RunNode {
  node_id: string;
  node_type: string;
  attempt: number;
  status: string;
  output_text: string | null;
  error: string | null;
}

export interface RunToolCall {
  id: string;
  node_id: string | null;
  tool_name: string;
  risk: Risk;
  status: string;
  arguments: Record<string, unknown>;
  result_preview: string | null;
  is_error: boolean | null;
  duration_ms: number | null;
}

export interface Run {
  id: string;
  kind: "agent" | "workflow";
  agent_id?: string | null;
  workflow_id?: string | null;
  status: RunStatus;
  name: string | null;
  input: { text: string; variables: Record<string, unknown>; attachments?: Pick<Attachment, "id" | "filename" | "kind">[] };
  output_text: string | null;
  output: { text?: string | null; sources?: string[]; guardrails?: GuardrailFlag[] } | null;
  error: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  /** Estimated from the tokens and the model that answered; null when its price isn't known. */
  cost_usd?: number | null;
  /** Set when a webhook started it. */
  webhook_id?: string | null;
  recoveries: number;
  created_at: string;
  /** Set when a schedule started it. */
  schedule_id?: string | null;
  /** Which saved version of the agent/workflow it ran. */
  definition_version?: number;
  /** The playground chat it is one message of. */
  conversation_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  nodes?: RunNode[];
  tool_calls?: RunToolCall[];
  approvals?: Approval[];
}

/** One message on the run's WebSocket. */
export type RunEvent =
  | { type: "snapshot"; run: Run }
  | { type: "ping" }
  | { type: "run_status"; status: RunStatus; error?: string | null }
  | { type: "node_status"; node_id: string; status: string; attempt?: number; preview?: string; error?: string }
  | { type: "agent_turn"; node_id: string; turn: number; tool_calls: string[] }
  | { type: "guardrail"; node_id: string; rule: string; severity: GuardrailFlag["severity"]; message: string }
  | { type: "tool_call"; node_id: string; phase: "started" | "finished" | "declined"; tool: string; risk?: Risk; is_error?: boolean; preview?: string; arguments?: Record<string, unknown> }
  | { type: "condition"; node_id: string; branch: string; target: string }
  | { type: "approval_requested"; approval_id: string; kind: Approval["kind"]; node_id?: string; tool?: string }
  | { type: "approval_resolved"; approval_id: string; status: string }
  | { type: "output"; text: string; sources?: string[] };
