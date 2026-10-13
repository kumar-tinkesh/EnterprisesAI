/**
 * The guided agent setup: its steps, and the pure rules behind them (profiles,
 * per-server tool access, what still needs attention before creating). The
 * components only render these; vitest covers them (tests/agent-wizard.test.ts).
 */

import { serverIdOf, toolName } from "@/lib/builder/graph";
import type { AgentConfig, AgentProfile, ApprovalPolicy, DraftAgent, GuardrailSettings, Risk } from "@/lib/builder/types";

export const WIZARD_STEPS = [
  { id: "describe", label: "Describe", title: "What should your agent do?", hint: "Describe it in your own words. The AI drafts everything else, and you can change any of it." },
  { id: "identity", label: "Identity", title: "Who is it?", hint: "Its name, its job, and the rules it works by. This is what the model is told on every run." },
  { id: "abilities", label: "Abilities", title: "What can it use?", hint: "The tools it may call and the documents it can search. It can't use anything that isn't listed here." },
  { id: "behaviour", label: "Behaviour", title: "How should it behave?", hint: "Safety checks, when it asks you first, and how it writes its answers." },
  { id: "engine", label: "Engine", title: "How hard should it think?", hint: "Pick a profile. It trades answer quality against speed and cost." },
  { id: "review", label: "Review", title: "Check it, then save it", hint: "A plain-language summary of everything above, and anything that still needs you." },
] as const;

export type WizardStepId = (typeof WIZARD_STEPS)[number]["id"];

export const stepIndex = (id: WizardStepId) => WIZARD_STEPS.findIndex((s) => s.id === id);

export const DEFAULT_APPROVALS: ApprovalPolicy = { read: false, edit: true, delete: true };

/** A new agent with nothing filled in (the "set it up by hand" path). */
export function blankAgent(profile?: AgentProfile): DraftAgent {
  const config: AgentConfig = { tool_ids: [], knowledge_base_ids: [], approvals: { ...DEFAULT_APPROVALS } };
  return { name: "", role: "", goal: "", instructions: "", llm_provider: "", llm_model: "", config: profile ? applyProfile(config, profile) : config };
}

type Plain = Record<string, unknown>;
const isPlain = (v: unknown): v is Plain => typeof v === "object" && v !== null && !Array.isArray(v);

/** Same rule as the backend's merge_config: nested sections merge key by key; lists and scalars are replaced. */
export function mergeConfig<T extends Plain>(base: T, overrides: Plain): T {
  const out: Plain = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    out[key] = isPlain(value) && isPlain(out[key]) ? mergeConfig(out[key] as Plain, value) : value;
  }
  return out as T;
}

export function applyProfile(config: AgentConfig, profile: AgentProfile): AgentConfig {
  return mergeConfig(config, profile.config as Plain);
}

/** The profile whose settings ``config`` still matches exactly, if any. */
export function matchingProfile(config: AgentConfig, profiles: AgentProfile[]): AgentProfile | null {
  const same = (a: unknown, b: unknown): boolean =>
    isPlain(b) ? isPlain(a) && Object.entries(b).every(([k, v]) => same(a[k], v)) : (a ?? null) === (b ?? null);
  return profiles.find((p) => same(config, p.config)) ?? null;
}

// ── Tools, per server ───────────────────────────────────────────────────────

/** Tool ids grouped by their server, servers in the order first seen. */
export function groupByServer(toolIds: string[]): { serverId: string; toolIds: string[] }[] {
  const groups = new Map<string, string[]>();
  for (const id of toolIds) {
    const server = serverIdOf(id) ?? "unknown";
    groups.set(server, [...(groups.get(server) ?? []), id]);
  }
  return Array.from(groups, ([serverId, ids]) => ({ serverId, toolIds: ids }));
}

export type Access = "none" | "read" | "readwrite" | "custom";
type ServerTool = { name: string; risk: Risk };

const PRESET_RISKS: Record<"read" | "readwrite", Risk[]> = { read: ["read"], readwrite: ["read", "edit"] };

/** A preset's tools on one server. Delete tools are never part of a preset —
 *  removing real records is always a deliberate tick. */
export function presetToolIds(serverId: string, tools: ServerTool[], preset: "read" | "readwrite"): string[] {
  return tools.filter((t) => PRESET_RISKS[preset].includes(t.risk)).map((t) => `mcp:${serverId}:${t.name}`);
}

/** Which preset (if any) the selection on this server is exactly. */
export function accessOf(serverId: string, selected: string[], tools: ServerTool[]): Access {
  const mine = new Set(selected.filter((id) => serverIdOf(id) === serverId));
  if (mine.size === 0) return "none";
  for (const preset of ["read", "readwrite"] as const) {
    const ids = presetToolIds(serverId, tools, preset);
    if (ids.length === mine.size && ids.every((id) => mine.has(id))) return preset;
  }
  return "custom";
}

/** ``toolIds`` with this server's tools replaced by ``ids`` (other servers untouched, order kept). */
export function replaceServerTools(toolIds: string[], serverId: string, ids: string[]): string[] {
  // Everything before the server's first tool belongs to other servers, so
  // its new tools go back in at that same spot.
  const at = toolIds.findIndex((id) => serverIdOf(id) === serverId);
  const others = toolIds.filter((id) => serverIdOf(id) !== serverId);
  const unique = Array.from(new Set(ids));
  return at < 0 ? [...others, ...unique] : [...others.slice(0, at), ...unique, ...others.slice(at)];
}

// ── The summary and what still needs attention ─────────────────────────────

const GUARDRAIL_LABELS: [keyof GuardrailSettings, string][] = [
  ["injection", "blocks attempts to override its instructions"],
  ["tool_injection", "ignores instructions hidden in tool results"],
  ["pii_input", "hides personal data from the model"],
  ["pii_output", "hides personal data in answers"],
  ["groundedness", "checks answers against its documents"],
];

export function guardrailsOn(g: GuardrailSettings | undefined): string[] {
  if (!g) return [];
  const on = GUARDRAIL_LABELS.filter(([k]) => g[k]).map(([, label]) => label);
  const rules = g.custom_rules?.length ?? 0;
  return rules ? [...on, `follows ${rules} rule${rules === 1 ? "" : "s"} of yours`] : on;
}

export function askFirstFor(approvals: Partial<ApprovalPolicy> | undefined): string[] {
  const a = { ...DEFAULT_APPROVALS, ...(approvals ?? {}) };
  return [a.read && "reading data", a.edit && "changing data", a.delete && "deleting anything"].filter(Boolean) as string[];
}

export interface Issue {
  /** "block" stops Create; "warn" is worth knowing but it can still be created. */
  level: "block" | "warn";
  message: string;
  step: WizardStepId;
  serverId?: string;
}

export function reviewIssues(
  draft: DraftAgent,
  ctx: { disconnected: { serverId: string; name: string }[]; knowledgeRecommended: boolean; needs: string },
): Issue[] {
  const issues: Issue[] = [];
  if (!draft.name.trim()) issues.push({ level: "block", message: "Give it a name.", step: "identity" });
  if (!draft.role.trim()) issues.push({ level: "block", message: "Give it a role.", step: "identity" });
  if (!draft.goal.trim()) issues.push({ level: "block", message: "Say what it should do (its goal).", step: "identity" });
  for (const s of ctx.disconnected) {
    issues.push({ level: "warn", message: `Connect ${s.name} — its tools can't run until you do.`, step: "abilities", serverId: s.serverId });
  }
  const tools = draft.config.tool_ids ?? [];
  const kbs = draft.config.knowledge_base_ids ?? [];
  if (!tools.length && ctx.needs.trim()) {
    issues.push({ level: "warn", message: `It needs to "${ctx.needs}", but it has no tools for that yet.`, step: "abilities" });
  }
  if (ctx.knowledgeRecommended && !kbs.length) {
    issues.push({ level: "warn", message: "It should answer from your documents, but no knowledge base is attached.", step: "abilities" });
  }
  if (draft.config.guardrails?.groundedness && !kbs.length) {
    issues.push({ level: "warn", message: "Answers are checked against its documents, but it has none.", step: "behaviour" });
  }
  return issues;
}

/** "send_email, search_emails" — short tool lists for the summary. */
export function toolList(ids: string[], max = 3): string {
  const names = ids.map(toolName);
  return names.length > max ? `${names.slice(0, max).join(", ")} +${names.length - max} more` : names.join(", ");
}
