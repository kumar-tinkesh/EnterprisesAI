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
  response?: { tone?: string; verbosity?: string; language?: string; citations?: string };
  tools?: { max_calls?: number; timeout_seconds?: number; on_failure?: string };
  reliability?: { retries?: number };
  approvals?: ApprovalPolicy;
  [key: string]: unknown;
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
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string | null;
}

export interface WorkflowConfig {
  max_run_seconds?: number;
  max_steps?: number;
  on_node_failure?: "abort" | "skip" | "retry";
  node_retry_count?: number;
  default_knowledge_base_ids?: string[];
  approvals?: ApprovalPolicy;
}

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
  output: { text?: string; sources?: string[] } | null;
  error: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  recoveries: number;
  created_at: string;
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
  | { type: "tool_call"; node_id: string; phase: "started" | "finished" | "declined"; tool: string; risk?: Risk; is_error?: boolean; preview?: string; arguments?: Record<string, unknown> }
  | { type: "condition"; node_id: string; branch: string; target: string }
  | { type: "approval_requested"; approval_id: string; kind: Approval["kind"]; node_id?: string; tool?: string }
  | { type: "approval_resolved"; approval_id: string; status: string }
  | { type: "output"; text: string; sources?: string[] };
