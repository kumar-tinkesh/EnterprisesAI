"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BookOpen, Bot, ChevronDown, ChevronRight, MessageSquareText, ShieldCheck, SlidersHorizontal, Sparkles, UserRoundCheck, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { AgentFields, type AgentSection } from "@/components/builder/agent-fields";
import { Field, Select, Textarea } from "@/components/builder/fields";
import { builderApi } from "@/lib/builder/api";
import { toolName } from "@/lib/builder/graph";
import type { Agent, AgentConfig, DraftAgent, WorkflowNode } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** What each step-level override replaces in the agent's config. */
const SECTION_KEYS: Record<Exclude<AgentSection, "identity">, (keyof AgentConfig)[]> = {
  model: ["llm", "reliability"],
  answers: ["response"],
  tools: ["tool_ids", "tools"],
  knowledge: ["knowledge_base_ids"],
  guardrails: ["guardrails"],
  approvals: ["approvals"],
};

const OVERRIDES: { id: Exclude<AgentSection, "identity">; title: string; Icon: typeof Bot }[] = [
  { id: "model", title: "Model & performance", Icon: SlidersHorizontal },
  { id: "answers", title: "How it answers", Icon: MessageSquareText },
  { id: "tools", title: "Tools and MCP", Icon: Wrench },
  { id: "knowledge", title: "Knowledge", Icon: BookOpen },
  { id: "guardrails", title: "Guardrails", Icon: ShieldCheck },
  { id: "approvals", title: "Ask before tools run", Icon: UserRoundCheck },
];

/** The goal a freshly added agent step starts with (lib/builder/graph.ts newNode). */
const NEW_AGENT_GOAL = "Describe what this step does";

const WIZARD: { id: "describe" | AgentSection; title: string }[] = [
  { id: "describe", title: "Describe" },
  { id: "identity", title: "Identity" },
  { id: "tools", title: "Tools" },
  { id: "knowledge", title: "Knowledge" },
  { id: "answers", title: "Answers" },
  { id: "model", title: "Model" },
  { id: "guardrails", title: "Safety" },
];

function summary(section: Exclude<AgentSection, "identity">, agent: { llm_model?: string; config?: AgentConfig }): string {
  const c = agent.config ?? {};
  switch (section) {
    case "model":
      return `${agent.llm_model || "Default model"}${c.llm?.temperature != null ? ` · temp ${c.llm.temperature}` : ""}`;
    case "answers":
      return c.response?.verbosity ?? "balanced";
    case "tools":
      return `${(c.tool_ids ?? []).length} tool${(c.tool_ids ?? []).length === 1 ? "" : "s"}`;
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
 * An agent step's popup. A new agent (a draft on the step) is built right here,
 * step by step; a saved agent shows Marketplace's "node override": each part
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
  if (node.draft_agent) return <AgentWizard draft={node.draft_agent} customizing={!!node.agent_id} token={token} onChange={(draft_agent) => onChange({ draft_agent })} />;
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
  const merged = mergeConfig(agent.config, overrides);
  const isOn = (s: Exclude<AgentSection, "identity">) => SECTION_KEYS[s].some((k) => k in overrides);
  const count = OVERRIDES.filter((o) => isOn(o.id)).length;

  const toggle = (s: Exclude<AgentSection, "identity">, on: boolean) => {
    const next = { ...overrides };
    for (const k of SECTION_KEYS[s]) {
      if (on) next[k] = (agent.config as Record<string, unknown>)?.[k] ?? (k === "tool_ids" || k === "knowledge_base_ids" ? [] : {});
      else delete next[k];
    }
    onChange({ config_overrides: Object.keys(next).length ? next : null });
    setOpen(on ? s : open);
  };
  const edit = (s: Exclude<AgentSection, "identity">, next: DraftAgent) => {
    const o = { ...overrides };
    for (const k of SECTION_KEYS[s]) o[k] = (next.config as Record<string, unknown>)?.[k];
    onChange({ config_overrides: o });
  };

  return (
    <div className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-semibold text-zinc-900">{agent.name}</span>
        <span className="text-[11px] text-indigo-600">· node override</span>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", count ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700")}>
          {count ? `${count} overridden for this step` : "Inheriting agent defaults"}
        </span>
      </div>

      <Accordion title="Agent overview" sub={agent.name} Icon={Bot} open={open === "overview"} onToggle={() => setOpen(open === "overview" ? null : "overview")}>
        <div className="space-y-2 text-xs">
          <p className="text-zinc-600"><span className="font-medium text-zinc-900">{agent.role}</span> — {agent.goal}</p>
          {(agent.config?.tool_ids ?? []).length > 0 && <p className="text-zinc-500">Tools: {(agent.config?.tool_ids ?? []).map(toolName).join(", ")}</p>}
          <Field label="Use a different agent">
            <Select value={agent.id} onChange={(e) => onChange({ agent_id: e.target.value, config_overrides: null })}>
              {!standaloneAgents.some((a) => a.id === agent.id) && <option value={agent.id}>{agent.name} (this workflow)</option>}
              {standaloneAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </Field>
          <Button size="sm" variant="outline" className="h-8" onClick={() => onChange({ draft_agent: { name: agent.name, role: agent.role, goal: agent.goal, instructions: agent.instructions, llm_provider: agent.llm_provider, llm_model: agent.llm_model, config: mergeConfig(agent.config, overrides) }, config_overrides: null })}>
            Customize the whole agent for this workflow
          </Button>
        </div>
      </Accordion>

      <p className="pt-1 text-[11px] text-zinc-500">Customize parameters for this step. Turned OFF parameters automatically use main agent defaults.</p>

      {OVERRIDES.map(({ id, title, Icon }) => {
        const on = isOn(id);
        return (
          <Accordion
            key={id}
            title={title}
            sub={on ? `overridden · ${summary(id, { llm_model: agent.llm_model, config: merged })}` : summary(id, agent)}
            Icon={Icon}
            open={open === id}
            onToggle={() => setOpen(open === id ? null : id)}
            action={
              <label className="flex cursor-pointer items-center gap-1 text-[10px] text-zinc-500" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" className="h-3.5 w-3.5 accent-indigo-600" aria-label={`Override ${title} for this step`} checked={on} onChange={(e) => toggle(id, e.target.checked)} />
                Override
              </label>
            }
          >
            {on ? (
              <div className="-mx-4">
                <AgentFields
                  value={{ name: agent.name, role: agent.role, goal: agent.goal, instructions: agent.instructions, config: merged }}
                  token={token}
                  only={[id]}
                  stepOverride
                  onChange={(next) => edit(id, next)}
                />
              </div>
            ) : (
              <p className="text-xs text-zinc-500">Using the agent&apos;s setting: {summary(id, agent)}. Turn on Override to change it for this step only.</p>
            )}
          </Accordion>
        );
      })}
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

/** A new (or customized) agent for this step, built in the popup: describe it, then each part in turn. */
function AgentWizard({ draft, customizing, token, onChange }: { draft: DraftAgent; customizing: boolean; token: string; onChange: (d: DraftAgent) => void }) {
  // A fresh step (placeholder goal) starts at "Describe"; a filled-in or customized one at its identity.
  const [step, setStep] = useState(customizing || (draft.goal && draft.goal !== NEW_AGENT_GOAL) ? 1 : 0);
  const [description, setDescription] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const fill = useMutation({
    mutationFn: () => builderApi.draftAgent(token, description),
    onSuccess: (d) => {
      onChange({ name: d.name, role: d.role, goal: d.goal, instructions: d.instructions, config: d.config });
      const connect = d.needs_connection.map((s) => s.server_name);
      setNote(connect.length ? `Filled in. Connect before running: ${connect.join(", ")}.` : "Filled in — check each part.");
      setStep(1);
    },
  });
  const current = WIZARD[step];

  return (
    <div>
      <div className="mx-4 mt-3 rounded-lg bg-indigo-50 px-3 py-2 text-[11px] text-indigo-800">
        {customizing ? "A copy of the agent for this workflow — the original stays as it is." : "A new agent for this workflow — it's created when you save."}
      </div>
      <ol className="flex flex-wrap gap-1 px-4 pt-3" aria-label="Agent setup steps">
        {WIZARD.map((s, i) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => setStep(i)}
              className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium cursor-pointer", i === step ? "bg-indigo-600 text-white" : i < step ? "bg-indigo-50 text-indigo-700" : "bg-zinc-100 text-zinc-500")}
            >
              {i + 1}. {s.title}
            </button>
          </li>
        ))}
      </ol>
      {note && <p className="mx-4 mt-2 text-[11px] text-emerald-700">{note}</p>}

      {current.id === "describe" ? (
        <div className="space-y-2 px-4 py-3">
          <Field label="What should this agent do?" hint="The AI fills in everything — name, instructions, tools from your connected systems — for you to check.">
            <Textarea rows={4} value={description} placeholder="Reads new support emails, finds the order in Shopify and drafts a reply" onChange={(e) => setDescription(e.target.value)} />
          </Field>
          {fill.isError && <p className="text-xs text-red-600">{fill.error instanceof Error ? fill.error.message : "Couldn't fill it in."}</p>}
          <div className="flex gap-2">
            <Button size="sm" disabled={fill.isPending || description.trim().length < 3} onClick={() => fill.mutate()}>
              {fill.isPending ? <Spinner className="h-4 w-4" /> : <Sparkles />} Fill with AI
            </Button>
            <Button size="sm" variant="outline" onClick={() => setStep(1)}>Set it up myself</Button>
          </div>
        </div>
      ) : (
        <AgentFields value={draft} token={token} only={[current.id as AgentSection, ...(current.id === "guardrails" ? (["approvals"] as AgentSection[]) : [])]} onChange={onChange} />
      )}

      <div className="flex justify-between border-t border-zinc-200 px-4 py-2.5">
        <Button size="sm" variant="outline" className="h-8" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
        {step < WIZARD.length - 1 ? (
          <Button size="sm" className="h-8" onClick={() => setStep(step + 1)}>Next: {WIZARD[step + 1].title}</Button>
        ) : (
          <span className="self-center text-[11px] text-zinc-500">Done — Save the workflow to create it.</span>
        )}
      </div>
    </div>
  );
}
