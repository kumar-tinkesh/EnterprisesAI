"use client";

/** Client for the builder API (backend :8002, /api/v1/builder). */

import { BACKEND_API_URL, request } from "@/lib/api";

import type {
  Agent,
  AgentConfig,
  AgentDraft,
  Approval,
  CheckResult,
  Run,
  ServerTools,
  ToolCandidate,
  Workflow,
  WorkflowConfig,
  WorkflowDraft,
  WorkflowEdge,
  WorkflowEditResult,
  WorkflowNode,
  WorkflowSummary,
} from "@/lib/builder/types";

const B = "/builder";

function call<T>(token: string, path: string, method = "GET", body?: unknown): Promise<T> {
  return request<T>(
    `${B}${path}`,
    { method, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) },
    token,
    BACKEND_API_URL,
  );
}

export interface AgentBody {
  name: string;
  role: string;
  goal: string;
  instructions?: string;
  llm_provider?: string;
  llm_model?: string;
  config?: AgentConfig;
  workflow_id?: string | null;
  expected_version?: number;
}

export interface WorkflowBody {
  name?: string;
  description?: string;
  nodes?: WorkflowNode[];
  edges?: WorkflowEdge[];
  config?: WorkflowConfig;
  expected_version?: number;
}

export const builderApi = {
  // Agents
  listAgents: (t: string) => call<Agent[]>(t, "/agents"),
  getAgent: (t: string, id: string) => call<Agent>(t, `/agents/${id}`),
  createAgent: (t: string, body: AgentBody) => call<Agent>(t, "/agents", "POST", body),
  updateAgent: (t: string, id: string, body: Partial<AgentBody>) => call<Agent>(t, `/agents/${id}`, "PATCH", body),
  deleteAgent: (t: string, id: string) => call<void>(t, `/agents/${id}`, "DELETE"),
  agentPreflight: (t: string, id: string) => call<CheckResult>(t, `/agents/${id}/preflight`),

  // Workflows
  listWorkflows: (t: string) => call<WorkflowSummary[]>(t, "/workflows"),
  getWorkflow: (t: string, id: string) => call<Workflow>(t, `/workflows/${id}`),
  createWorkflow: (t: string, body: WorkflowBody) => call<Workflow>(t, "/workflows", "POST", body),
  updateWorkflow: (t: string, id: string, body: WorkflowBody) => call<Workflow>(t, `/workflows/${id}`, "PATCH", body),
  deleteWorkflow: (t: string, id: string) => call<void>(t, `/workflows/${id}`, "DELETE"),
  validateWorkflow: (t: string, body: { nodes: WorkflowNode[]; edges: WorkflowEdge[]; config: WorkflowConfig; workflow_id?: string }) =>
    call<CheckResult>(t, "/workflows/validate", "POST", body),
  workflowPreflight: (t: string, id: string) => call<CheckResult>(t, `/workflows/${id}/preflight`, "POST"),

  // Runs
  startAgentRun: (t: string, id: string, input: string) => call<Run>(t, `/agents/${id}/runs`, "POST", { input }),
  startWorkflowRun: (t: string, id: string, input: string, variables: Record<string, unknown>) =>
    call<Run>(t, `/workflows/${id}/runs`, "POST", { input, variables }),
  getRun: (t: string, id: string) => call<Run>(t, `/runs/${id}`),
  listRuns: (t: string, params: { agent_id?: string; workflow_id?: string }) =>
    call<Run[]>(t, `/runs?${new URLSearchParams(params as Record<string, string>).toString()}`),
  cancelRun: (t: string, id: string) => call<Run>(t, `/runs/${id}/cancel`, "POST"),
  decide: (t: string, approvalId: string, decision: "approve" | "reject" | "edit", args?: Record<string, unknown>) =>
    call<Approval>(t, `/approvals/${approvalId}`, "POST", { decision, ...(args ? { arguments: args } : {}) }),

  // Tools and the assistant
  searchTools: (t: string, q: string, limit = 8) =>
    call<ToolCandidate[]>(t, `/tools/search?${new URLSearchParams({ q, limit: String(limit) }).toString()}`),
  serverTools: (t: string, serverId: string) => call<ServerTools>(t, `/servers/${serverId}/tools`),
  draftAgent: (t: string, description: string) => call<AgentDraft>(t, "/assist/agent", "POST", { description }),
  draftWorkflow: (t: string, description: string) => call<WorkflowDraft>(t, "/assist/workflow", "POST", { description }),
  editWorkflow: (t: string, body: { instruction: string; name: string; nodes: WorkflowNode[]; edges: WorkflowEdge[]; config: WorkflowConfig; workflow_id?: string }) =>
    call<WorkflowEditResult>(t, "/assist/workflow-edit", "POST", body),
  improveText: (t: string, field: string, text: string, context = "") =>
    call<{ text: string }>(t, "/assist/improve-text", "POST", { field, text, context }),
};

/** ws(s)://…/api/v1/builder/runs/{id}/events?token=… — browsers can't send headers on a WebSocket. */
export function runEventsUrl(runId: string, token: string): string {
  const base = BACKEND_API_URL.replace(/^http/, "ws");
  return `${base}${B}/runs/${runId}/events?token=${encodeURIComponent(token)}`;
}
