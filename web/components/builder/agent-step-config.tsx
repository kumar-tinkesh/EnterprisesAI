"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BookOpen, Bot, Brain, ChevronDown, ChevronRight, MessageSquareText, ShieldCheck, SlidersHorizontal, Sparkles, UserRoundCheck, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { AgentFields, type AgentSection } from "@/components/builder/agent-fields";
import { Field, OverrideParams, Select, Textarea } from "@/components/builder/fields";
import { builderApi } from "@/lib/builder/api";
import { overriddenParams } from "@/lib/builder/graph";
import type { Agent, AgentConfig, DraftAgent, WorkflowNode } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

type OverrideId = "model" | "answers" | "tools" | "knowledge" | "memory" | "guardrails" | "approvals";

/** The step can run its agent on another model: these sit in its overrides beside the config keys. */
const MODEL_KEYS = ["llm_model", "llm_provider"] as const;

/** What each step-level override replaces in the agent's config. */
const SECTION_KEYS: Record<OverrideId, string[]> = {
  model: ["llm", "reliability", ...MODEL_KEYS],
  answers: ["response"],
  tools: ["tool_ids", "tools"],
  knowledge: ["knowledge_base_ids"],
  memory: ["memory"],
  guardrails: ["guardrails"],
  approvals: ["approvals"],
};

/** The fields each override shows. */
const SECTION_FIELDS: Record<OverrideId, AgentSection[]> = {
  model: ["model"],
  answers: ["answers"],
  tools: ["tools", "limits"],
  knowledge: ["knowledge"],
  memory: ["memory"],
  guardrails: ["guardrails"],
  approvals: ["approvals"],
};

const OVERRIDES: { id: OverrideId; title: string; Icon: typeof Bot }[] = [
  { id: "model", title: "Model & performance", Icon: SlidersHorizontal },
  { id: "answers", title: "How it answers", Icon: MessageSquareText },
  { id: "tools", title: "Tools and MCP", Icon: Wrench },
  { id: "knowledge", title: "Knowledge", Icon: BookOpen },
  { id: "memory", title: "Memory", Icon: Brain },
  { id: "guardrails", title: "Guardrails", Icon: ShieldCheck },
  { id: "approvals", title: "Ask before tools run", Icon: UserRoundCheck },
];

/** A setting switched on for the step starts from the agent's value, or this when the agent has none. */
const PARAM_DEFAULTS: Record<string, unknown> = {
  "llm.temperature": 0.3, "llm.max_output_tokens": null, "llm.reasoning_effort": "auto", "llm.stop_sequences": [],
  "reliability.retries": 0, "reliability.request_timeout_seconds": null, "reliability.fallback_model": "",
  "reliability.retry_on": ["rate_limit", "timeout", "server"],
  "response.tone": "", "response.verbosity": "balanced", "response.language": "auto", "response.formats": [], "response.citations": "always",
  tool_ids: [], "tools.max_calls": 8, "tools.timeout_seconds": 30, "tools.on_failure": "continue",
  knowledge_base_ids: [], "memory.enabled": false, "memory.max_items": 50,
  "approvals.read": false, "approvals.edit": true, "approvals.delete": true,
  "guardrails.injection": false, "guardrails.tool_injection": false, "guardrails.pii_input": false, "guardrails.pii_output": false,
  "guardrails.groundedness": false, "guardrails.groundedness_mode": "fast", "guardrails.groundedness_min": 0.45,
  "guardrails.custom_rules": [], "guardrails.on_violation": "flag",
};

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

function valueAt(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((o, k) => (isObject(o) ? o[k] : undefined), obj);
}

/** The goal agent steps added before the step picker existed started with. */
const NEW_AGENT_GOAL = "Describe what this step does";

function summary(section: OverrideId, agent: { llm_model?: string; config?: AgentConfig }): string {
  const c = agent.config ?? {};
  switch (section) {
    case "model": {
      const effort = c.llm?.reasoning_effort && c.llm.reasoning_effort !== "auto" ? ` · ${c.llm.reasoning_effort} effort` : "";
      return `${agent.llm_model || "Default model"}${c.llm?.temperature != null ? ` · temp ${c.llm.temperature}` : ""}${effort}`;
    }
    case "memory":
      return c.memory?.enabled ? `On · up to ${c.memory.max_items ?? 50} facts a person` : "Off";
    case "answers":
      return c.response?.verbosity ?? "balanced";
    case "tools":
      return `${(c.tool_ids ?? []).length} tool${(c.tool_ids ?? []).length === 1 ? "" : "s"} · ${c.tools?.on_failure === "retry" ? "retries failures" : c.tools?.on_failure === "stop" ? "stops on failure" : `max ${c.tools?.max_calls ?? 8} calls`}`;
    case "knowledge":
      return (c.knowledge_base_ids ?? []).length ? `${(c.knowledge_base_ids ?? []).length} knowledge base(s)` : "Agent default knowledge";
    case "guardrails": {
      const g = c.guardrails ?? {};
      const on = [g.injection, g.tool_injection, g.pii_input, g.pii_output, g.groundedness].filter(Boolean).length + (g.custom_rules?.length ?? 0);
      return on ? `${on} on` : "Off / Default";
    }
    case "approvals": {
      const a = { read: false, edit: true, delete: true, ...(c.approvals ?? {}) };
      return (["read", "edit", "delete"] as const).filter((k) => a[k]).join(", ") || "Never asks";
    }
  }
}

function mergeConfig(base: AgentConfig | undefined, overrides: Record<string, unknown> | null | undefined): AgentConfig {
  const out: Record<string, unknown> = { ...(base ?? {}) };
  for (const [k, v] of Object.entries(overrides ?? {})) {
    out[k] = v && typeof v === "object" && !Array.isArray(v) && typeof out[k] === "object" && out[k] && !Array.isArray(out[k])
      ? { ...(out[k] as object), ...(v as object) }
      : v;
  }
  return out as AgentConfig;
}

/**
 * An agent step's popup. A new or customized agent (a draft on the step) is edited right here;
 * a saved agent shows Marketplace's "node override": each part
 * inherits the agent's setting until switched on for this step only.
 */
export function AgentStepConfig({
  node,
  agents,
  standaloneAgents,
  token,
  onChange,
}: {
  node: WorkflowNode;
  agents: Record<string, Agent>;
  standaloneAgents: Agent[];
  token: string;
  onChange: (p: Partial<WorkflowNode>) => void;
}) {
  const saved = node.agent_id ? agents[node.agent_id] : undefined;
  if (node.draft_agent) return <DraftConfig node={node} draft={node.draft_agent} original={saved} token={token} onChange={onChange} />;
  if (!saved) {
    return (
      <div className="space-y-3 px-4 py-4">
        <p className="text-xs text-zinc-500">Build a new agent for this step, or use one you already have.</p>
        <Button size="sm" onClick={() => onChange({ agent_id: null, draft_agent: { name: "New agent", role: "Assistant", goal: "", instructions: "", config: {} } })}>
          <Sparkles /> Create a new agent
        </Button>
        {standaloneAgents.length > 0 && (
          <Field label="…or use an existing agent">
            <Select value="" onChange={(e) => e.target.value && onChange({ agent_id: e.target.value })}>
              <option value="">Choose…</option>
              {standaloneAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </Field>
        )}
      </div>
    );
  }
  return <StepOverrides node={node} agent={saved} standaloneAgents={standaloneAgents} token={token} onChange={onChange} />;
}

function StepOverrides({
  node,
  agent,
  standaloneAgents,
  token,
  onChange,
}: {
  node: WorkflowNode;
  agent: Agent;
  standaloneAgents: Agent[];
  token: string;
  onChange: (p: Partial<WorkflowNode>) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const overrides = (node.config_overrides ?? {}) as Record<string, unknown>;
  const { llm_model: stepModel, llm_provider: stepProvider, ...configOverrides } = overrides;
  const merged = mergeConfig(agent.config, configOverrides);
  const model = (stepModel as string | undefined) || agent.llm_model;
  const provider = (stepProvider as string | undefined) || agent.llm_provider;
  const on = overriddenParams(overrides);
  const partOf = (path: string) => OVERRIDES.find((o) => SECTION_KEYS[o.id].includes(path.split(".")[0]))?.id;
  const attempts = node.retry?.max_attempts ?? 1;
  const isModelKey = (k: string) => (MODEL_KEYS as readonly string[]).includes(k);

  // Switching a setting on starts it at the agent's value; off hands it back to the agent.
  const params = {
    isOn: (path: string) => on.includes(path),
    toggle: (path: string, enable: boolean) => {
      const [top, sub] = path.split(".");
      const next = { ...overrides };
      if (enable) {
        const own = isModelKey(top) ? (agent as unknown as Record<string, unknown>)[top] ?? "" : valueAt(agent.config, path);
        const value = own === undefined ? (PARAM_DEFAULTS[path] ?? null) : own;
        if (sub) next[top] = { ...(isObject(next[top]) ? next[top] : {}), [sub]: value };
        else next[top] = value;
      } else if (sub && isObject(next[top])) {
        const { [sub]: _gone, ...rest } = next[top] as Record<string, unknown>;
        if (Object.keys(rest).length) next[top] = rest;
        else delete next[top];
      } else delete next[top];
      onChange({ config_overrides: Object.keys(next).length ? next : null });
    },
  };
  // An edit: the settings switched on take their new values.
  const edit = (next: DraftAgent) => {
    const o = { ...overrides };
    for (const path of on) {
      const [top, sub] = path.split(".");
      const value = isModelKey(top) ? (next as unknown as Record<string, unknown>)[top] : valueAt(next.config, path);
      if (sub) o[top] = { ...(isObject(o[top]) ? o[top] : {}), [sub]: value };
      else o[top] = value;
    }
    onChange({ config_overrides: o });
  };

  return (
    <div className="space-y-2 px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", on.length ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700")}>
          {on.length ? `${on.length} setting${on.length === 1 ? "" : "s"} changed for this step` : "Inheriting agent defaults"}
        </span>
        {on.length > 0 && (
          <button type="button" className="ml-auto text-[11px] font-medium text-indigo-600 hover:text-indigo-500 cursor-pointer" onClick={() => onChange({ config_overrides: null })}>
            Reset
          </button>
        )}
      </div>

      <Accordion
        title="Agent overview"
        sub={`${node.label || agent.name}${attempts > 1 ? ` · ${attempts} attempts` : ""}`}
        Icon={Bot}
        open={open === "overview"}
        onToggle={() => setOpen(open === "overview" ? null : "overview")}
      >
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-[1fr_5.5rem] gap-2">
            <Field label="Step name">
              <Input className="h-8 text-xs" value={node.label ?? ""} placeholder={agent.name} onChange={(e) => onChange({ label: e.target.value || null })} />
            </Field>
            <Field label="Attempts">
              <Input
                className="h-8 text-xs"
                type="number"
                min={1}
                max={5}
                title="How many times the step is tried if it fails"
                value={attempts}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  onChange({ retry: n > 1 ? { max_attempts: Math.min(5, n) } : null });
                }}
              />
            </Field>
          </div>
          <dl className="space-y-1.5">
            <div><dt className="font-medium text-zinc-900">Goal</dt><dd className="text-zinc-600">{agent.goal || "—"}</dd></div>
            <div><dt className="font-medium text-zinc-900">Role</dt><dd className="text-zinc-600">{agent.role || "—"}</dd></div>
            {agent.instructions && <div><dt className="font-medium text-zinc-900">Instructions</dt><dd className="line-clamp-3 text-zinc-600" title={agent.instructions}>{agent.instructions}</dd></div>}
          </dl>
          <Field label="Use a different agent">
            <Select value={agent.id} onChange={(e) => onChange({ agent_id: e.target.value, config_overrides: null })}>
              {!standaloneAgents.some((a) => a.id === agent.id) && <option value={agent.id}>{agent.name} (this workflow)</option>}
              {standaloneAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </Field>
          <Button size="sm" variant="outline" className="h-8 w-full text-xs" onClick={() => onChange({ draft_agent: { name: agent.name, role: agent.role, goal: agent.goal, instructions: agent.instructions, llm_provider: provider, llm_model: model, config: merged }, config_overrides: null })}>
            Customize the whole agent here
          </Button>
        </div>
      </Accordion>

      <p className="pt-1 text-[11px] text-zinc-500">Switch a setting on to change it for this step only. Settings left off use the agent&apos;s own.</p>

      <OverrideParams.Provider value={params}>
        {OVERRIDES.map(({ id, title, Icon }) => {
          const changed = on.filter((p) => partOf(p) === id).length;
          return (
            <Accordion
              key={id}
              title={title}
              sub={summary(id, { llm_model: model, config: merged })}
              Icon={Icon}
              open={open === id}
              onToggle={() => setOpen(open === id ? null : id)}
              action={changed > 0 && <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">{changed} changed</span>}
            >
              <div className="-mx-4 -my-3">
                <AgentFields
                  value={{ name: agent.name, role: agent.role, goal: agent.goal, instructions: agent.instructions, llm_model: model, llm_provider: provider, config: merged }}
                  token={token}
                  only={SECTION_FIELDS[id]}
                  stepOverride
                  onChange={edit}
                />
              </div>
            </Accordion>
          );
        })}
      </OverrideParams.Provider>
    </div>
  );
}

function Accordion({
  title,
  sub,
  Icon,
  open,
  onToggle,
  action,
  children,
}: {
  title: string;
  sub: string;
  Icon: typeof Bot;
  open: boolean;
  onToggle: () => void;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50">
      <div role="button" tabIndex={0} onClick={onToggle} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onToggle()} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left cursor-pointer">
        <Icon className="h-4 w-4 shrink-0 text-zinc-400" />
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-semibold text-zinc-900">{title}</span>
          <span className="block truncate text-[10.5px] text-zinc-500">{sub}</span>
        </span>
        {action}
        {open ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
      </div>
      {open && <div className="border-t border-zinc-200 px-4 py-3">{children}</div>}
    </div>
  );
}

/**
 * A new or customized agent (a draft on the step), laid out like a saved agent's step: an overview
 * with the step's name, attempts and the agent's identity, then one fold per part — edited directly,
 * since a draft is this workflow's own copy. A fresh step opens on "Describe with AI".
 */
function DraftConfig({
  node,
  draft,
  original,
  token,
  onChange,
}: {
  node: WorkflowNode;
  draft: DraftAgent;
  /** The agent this draft was customized from, when it still exists. */
  original?: Agent;
  token: string;
  onChange: (p: Partial<WorkflowNode>) => void;
}) {
  const fresh = !original && (!draft.goal || draft.goal === NEW_AGENT_GOAL);
  const [open, setOpen] = useState<string | null>(fresh ? "describe" : null);
  const [description, setDescription] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const attempts = node.retry?.max_attempts ?? 1;
  const setDraft = (draft_agent: DraftAgent) => onChange({ draft_agent });
  const fill = useMutation({
    mutationFn: () => builderApi.draftAgent(token, description),
    onSuccess: (d) => {
      setDraft({ ...draft, name: d.name, role: d.role, goal: d.goal, instructions: d.instructions, config: d.config });
      const connect = d.needs_connection.map((s) => s.server_name);
      setNote(connect.length ? `Filled in. Connect before running: ${connect.join(", ")}.` : "Filled in — check each part.");
      setOpen("overview");
    },
  });

  return (
    <div className="space-y-2 px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", original ? "bg-amber-50 text-amber-700" : "bg-indigo-50 text-indigo-700")}>
          {original ? "Customized for this workflow" : "New agent for this workflow"}
        </span>
        {original && (
          <button type="button" className="ml-auto text-[11px] font-medium text-indigo-600 hover:text-indigo-500 cursor-pointer" onClick={() => onChange({ draft_agent: null })}>
            Undo customize
          </button>
        )}
      </div>
      <p className="text-[11px] text-zinc-500">
        {original ? `A copy of “${original.name}” — the original stays as it is.` : "It's created when you save the workflow."}
      </p>
      {note && <p className="text-[11px] text-emerald-700">{note}</p>}

      {!original && (
        <Accordion title="Describe with AI" sub="The AI fills in every part for you to check" Icon={Sparkles} open={open === "describe"} onToggle={() => setOpen(open === "describe" ? null : "describe")}>
          <div className="space-y-2 text-xs">
            <Field label="What should this agent do?" hint="Name, instructions, tools from your connected systems — all filled in.">
              <Textarea rows={4} value={description} placeholder="Reads new support emails, finds the order in Shopify and drafts a reply" onChange={(e) => setDescription(e.target.value)} />
            </Field>
            {fill.isError && <p className="text-xs text-red-600">{fill.error instanceof Error ? fill.error.message : "Couldn't fill it in."}</p>}
            <Button size="sm" className="h-8 text-xs" disabled={fill.isPending || description.trim().length < 3} onClick={() => fill.mutate()}>
              {fill.isPending ? <Spinner className="h-4 w-4" /> : <Sparkles />} Fill with AI
            </Button>
          </div>
        </Accordion>
      )}

      <Accordion
        title="Agent overview"
        sub={`${node.label || draft.name}${attempts > 1 ? ` · ${attempts} attempts` : ""}`}
        Icon={Bot}
        open={open === "overview"}
        onToggle={() => setOpen(open === "overview" ? null : "overview")}
      >
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-[1fr_5.5rem] gap-2">
            <Field label="Step name">
              <Input className="h-8 text-xs" value={node.label ?? ""} placeholder={draft.name} onChange={(e) => onChange({ label: e.target.value || null })} />
            </Field>
            <Field label="Attempts">
              <Input
                className="h-8 text-xs"
                type="number"
                min={1}
                max={5}
                title="How many times the step is tried if it fails"
                value={attempts}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  onChange({ retry: n > 1 ? { max_attempts: Math.min(5, n) } : null });
                }}
              />
            </Field>
          </div>
          <div className="-mx-4 -mb-3">
            <AgentFields value={draft} token={token} only={["identity"]} onChange={setDraft} />
          </div>
        </div>
      </Accordion>

      {OVERRIDES.map(({ id, title, Icon }) => (
        <Accordion
          key={id}
          title={title}
          sub={summary(id, draft)}
          Icon={Icon}
          open={open === id}
          onToggle={() => setOpen(open === id ? null : id)}
        >
          <div className="-mx-4 -my-3">
            <AgentFields value={draft} token={token} only={SECTION_FIELDS[id]} onChange={setDraft} />
          </div>
        </Accordion>
      ))}
    </div>
  );
}
