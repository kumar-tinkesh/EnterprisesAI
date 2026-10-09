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
  status: RunStatus;
  name: string | null;
  input: { text: string; variables: Record<string, unknown> };
  output_text: string | null;
  output: { text?: string | null; sources?: string[]; guardrails?: GuardrailFlag[] } | null;
  error: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  recoveries: number;
  created_at: string;
  /** Set when a schedule started it. */
  schedule_id?: string | null;
  /** Which saved version of the agent/workflow it ran. */
  definition_version?: number;
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
