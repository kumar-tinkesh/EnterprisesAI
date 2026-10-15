"use client";

/** Client for the builder API (backend :8002, /api/v1/builder). */

import { BACKEND_API_URL, request } from "@/lib/api";

import type {
  Agent,
  AgentConfig,
  AgentFile,
  AgentMemory,
  Attachment,
  AgentRequirements,
  Usage,
  Webhook,
  WebhookCreated,
  AgentProfile,
  Health,
  Insights,
  Overview,
  Published,
  AnswerDepth,
  AgentDraft,
  Approval,
  ChatRef,
  CheckResult,
  Conversation,
  GuardrailSettings,
  Run,
  PublicKey,
  PublicKeyCreated,
  PublishCheck,
  Schedule,
  SchedulePreview,
  TestCase,
  TestCategory,
  TestRun,
  Version,
  VersionDetail,
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

  // Memory, usage, triggers, requirements, files
  listMemories: (t: string, id: string) => call<AgentMemory[]>(t, `/agents/${id}/memories`),
  addMemory: (t: string, id: string, content: string) => call<AgentMemory>(t, `/agents/${id}/memories`, "POST", { content }),
  forgetMemory: (t: string, id: string, memoryId: string) => call<void>(t, `/agents/${id}/memories/${memoryId}`, "DELETE"),
  forgetAllMemories: (t: string, id: string) => call<void>(t, `/agents/${id}/memories`, "DELETE"),
  usage: (t: string, kind: "agent" | "workflow", id: string, days = 30) => call<Usage>(t, `/${kind}s/${id}/usage?days=${days}`),
  listWebhooks: (t: string, agentId: string) => call<Webhook[]>(t, `/agents/${agentId}/webhooks`),
  createWebhook: (t: string, agentId: string, body: { name: string; instruction: string; requests_per_minute: number }) =>
    call<WebhookCreated>(t, `/agents/${agentId}/webhooks`, "POST", body),
  updateWebhook: (t: string, id: string, body: Partial<Pick<Webhook, "name" | "instruction" | "enabled" | "requests_per_minute">>) =>
    call<Webhook>(t, `/webhooks/${id}`, "PATCH", body),
  deleteWebhook: (t: string, id: string) => call<void>(t, `/webhooks/${id}`, "DELETE"),
  agentRequirements: (t: string, id: string) => call<AgentRequirements>(t, `/agents/${id}/requirements`),
  exportAgent: (t: string, id: string) => call<AgentFile>(t, `/agents/${id}/export`),
  importAgent: (t: string, file: AgentFile) => call<{ agent: Agent; skipped: string[] }>(t, "/agents/import", "POST", file),
  uploadAttachment: (t: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Attachment>(`${B}/attachments`, { method: "POST", body }, t, BACKEND_API_URL);
  },
  deleteAttachment: (t: string, id: string) => call<void>(t, `/attachments/${id}`, "DELETE"),

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
  startAgentRun: (t: string, id: string, input: string, depth: AnswerDepth = "auto", chat: ChatRef = {}, attachmentIds: string[] = []) =>
    call<Run>(t, `/agents/${id}/runs`, "POST", { input, depth, ...chat, ...(attachmentIds.length ? { attachment_ids: attachmentIds } : {}) }),
  startWorkflowRun: (t: string, id: string, input: string, variables: Record<string, unknown>, depth: AnswerDepth = "auto", chat: ChatRef = {}) =>
    call<Run>(t, `/workflows/${id}/runs`, "POST", { input, variables, depth, ...chat }),
  /** Run one step by itself, as it is on the canvas (unsaved edits too). */
  testStep: (t: string, workflowId: string, node: WorkflowNode, input: string, variables: Record<string, unknown> = {}) =>
    call<Run>(t, `/workflows/${workflowId}/steps/test`, "POST", { node, input, variables }),

  // Playground chats
  listConversations: (t: string, params: { agent_id?: string; workflow_id?: string }) =>
    call<Conversation[]>(t, `/conversations?${new URLSearchParams(params as Record<string, string>).toString()}`),
  conversationRuns: (t: string, id: string) => call<Run[]>(t, `/conversations/${id}/runs`),
  renameConversation: (t: string, id: string, title: string) => call<Conversation>(t, `/conversations/${id}`, "PATCH", { title }),
  deleteConversation: (t: string, id: string) => call<void>(t, `/conversations/${id}`, "DELETE"),
  workflowKnowledge: (t: string, id: string) => call<{ knowledge_base_id: string | null }>(t, `/workflows/${id}/knowledge`),
  createWorkflowKnowledge: (t: string, id: string) => call<{ knowledge_base_id: string }>(t, `/workflows/${id}/knowledge`, "POST"),
  getRun: (t: string, id: string) => call<Run>(t, `/runs/${id}`),
  listRuns: (t: string, params: { agent_id?: string; workflow_id?: string; limit?: number }) =>
    call<Run[]>(t, `/runs?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()}`),
  /** Decisions waiting on the signed-in user (pending by default). */
  listApprovals: (t: string) => call<Approval[]>(t, "/approvals"),
  cancelRun: (t: string, id: string) => call<Run>(t, `/runs/${id}/cancel`, "POST"),
  decide: (t: string, approvalId: string, decision: "approve" | "reject" | "edit", args?: Record<string, unknown>) =>
    call<Approval>(t, `/approvals/${approvalId}`, "POST", { decision, ...(args ? { arguments: args } : {}) }),

  // Versions
  listVersions: (t: string, kind: "agent" | "workflow", id: string) => call<Version[]>(t, `/${kind}s/${id}/versions`),
  getVersion: (t: string, kind: "agent" | "workflow", id: string, version: number) =>
    call<VersionDetail>(t, `/${kind}s/${id}/versions/${version}`),
  restoreAgentVersion: (t: string, id: string, version: number, expected_version: number) =>
    call<Agent>(t, `/agents/${id}/versions/${version}/restore`, "POST", { expected_version }),
  restoreWorkflowVersion: (t: string, id: string, version: number, expected_version: number) =>
    call<Workflow>(t, `/workflows/${id}/versions/${version}/restore`, "POST", { expected_version }),

  // Tests
  listTests: (t: string, kind: "agent" | "workflow", id: string) => call<TestCase[]>(t, `/${kind}s/${id}/tests`),
  createTest: (t: string, kind: "agent" | "workflow", id: string, body: { title?: string; input: string; expectation: string; category: TestCategory; variables?: Record<string, unknown> }) =>
    call<TestCase>(t, `/${kind}s/${id}/tests`, "POST", body),
  updateTest: (t: string, caseId: string, body: Partial<Pick<TestCase, "title" | "input" | "expectation" | "category" | "variables">>) =>
    call<TestCase>(t, `/tests/${caseId}`, "PATCH", body),
  deleteTest: (t: string, caseId: string) => call<void>(t, `/tests/${caseId}`, "DELETE"),
  generateTests: (t: string, kind: "agent" | "workflow", id: string, count: number, categories: TestCategory[]) =>
    call<TestCase[]>(t, `/${kind}s/${id}/tests/generate`, "POST", { count, categories }),
  startTestRun: (t: string, kind: "agent" | "workflow", id: string) => call<TestRun>(t, `/${kind}s/${id}/test-runs`, "POST", {}),
  listTestRuns: (t: string, kind: "agent" | "workflow", id: string) => call<TestRun[]>(t, `/${kind}s/${id}/test-runs`),
  getTestRun: (t: string, id: string) => call<TestRun>(t, `/test-runs/${id}`),
  cancelTestRun: (t: string, id: string) => call<TestRun>(t, `/test-runs/${id}/cancel`, "POST"),

  // Publishing
  publishCheck: (t: string, kind: "agent" | "workflow", id: string, version?: number | null) =>
    call<PublishCheck>(t, `/${kind}s/${id}/publish-check${version ? `?version=${version}` : ""}`),
  listPublicKeys: (t: string, kind: "agent" | "workflow", id: string) => call<PublicKey[]>(t, `/${kind}s/${id}/public-keys`),
  createPublicKey: (
    t: string, kind: "agent" | "workflow", id: string,
    body: { name: string; version: number | null; allowed_origins: string[]; requests_per_minute: number; daily_quota: number | null; acknowledge_write_tools: boolean },
  ) => call<PublicKeyCreated>(t, `/${kind}s/${id}/public-keys`, "POST", body),
  updatePublicKey: (t: string, keyId: string, body: { status?: "active" | "paused"; version?: number; latest?: boolean; name?: string }) =>
    call<PublicKey>(t, `/public-keys/${keyId}`, "PATCH", body),
  revokePublicKey: (t: string, keyId: string) => call<void>(t, `/public-keys/${keyId}`, "DELETE"),
  overview: (t: string, days = 7) => call<Overview>(t, `/overview?days=${days}`),
  health: (t: string, kind: "agent" | "workflow", id: string) => call<Health>(t, `/${kind}s/${id}/health`),
  insights: (t: string, days = 7) => call<Insights>(t, `/insights?days=${days}`),
  published: (t: string, days = 14) => call<Published>(t, `/published?days=${days}`),

  // Schedules
  listSchedules: (t: string, params: { agent_id?: string; workflow_id?: string }) =>
    call<Schedule[]>(t, `/schedules?${new URLSearchParams(params as Record<string, string>).toString()}`),
  createSchedule: (t: string, body: { agent_id: string; cron: string; timezone: string; input: string; enabled?: boolean }) =>
    call<Schedule>(t, "/schedules", "POST", body),
  updateSchedule: (t: string, id: string, body: { cron?: string; timezone?: string; input?: string; enabled?: boolean }) =>
    call<Schedule>(t, `/schedules/${id}`, "PATCH", body),
  deleteSchedule: (t: string, id: string) => call<void>(t, `/schedules/${id}`, "DELETE"),
  runSchedule: (t: string, id: string) => call<{ run_id: string }>(t, `/schedules/${id}/run`, "POST"),
  previewSchedule: (t: string, cron: string, timezone: string) =>
    call<SchedulePreview>(t, "/schedules/preview", "POST", { cron, timezone }),

  // Tools and the assistant
  searchTools: (t: string, q: string, limit = 8) =>
    call<ToolCandidate[]>(t, `/tools/search?${new URLSearchParams({ q, limit: String(limit) }).toString()}`),
  serverTools: (t: string, serverId: string) => call<ServerTools>(t, `/servers/${serverId}/tools`),
  agentProfiles: (t: string) => call<AgentProfile[]>(t, "/assist/agent-profiles"),
  draftAgent: (t: string, description: string) => call<AgentDraft>(t, "/assist/agent", "POST", { description }),
  draftWorkflow: (t: string, description: string) => call<WorkflowDraft>(t, "/assist/workflow", "POST", { description }),
  editWorkflow: (t: string, body: { instruction: string; name: string; nodes: WorkflowNode[]; edges: WorkflowEdge[]; config: WorkflowConfig; workflow_id?: string }) =>
    call<WorkflowEditResult>(t, "/assist/workflow-edit", "POST", { ...body, timezone: browserTimezone() }),
  suggestGuardrails: (
    t: string,
    body: { name: string; role: string; goal: string; instructions: string; tool_ids: string[]; has_knowledge: boolean },
  ) => call<{ guardrails: GuardrailSettings; reasoning: string }>(t, "/assist/guardrails", "POST", body),
  improveText: (t: string, field: string, text: string, context = "") =>
    call<{ text: string }>(t, "/assist/improve-text", "POST", { field, text, context }),
};

/** The public API (no login; a publishable key): what published agents/workflows are called on. */
export const PUBLIC_API_URL = `${BACKEND_API_URL}/public`;

/** The viewer's IANA timezone ("Asia/Kolkata"); what "every day at 9" means to them. */
export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** ws(s)://…/api/v1/builder/runs/{id}/events?token=… — browsers can't send headers on a WebSocket. */
export function runEventsUrl(runId: string, token: string): string {
  const base = BACKEND_API_URL.replace(/^http/, "ws");
  return `${base}${B}/runs/${runId}/events?token=${encodeURIComponent(token)}`;
}
