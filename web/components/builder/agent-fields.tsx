"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Sparkles, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Section, Select, Textarea, Toggle } from "@/components/builder/fields";
import { GuardrailFields } from "@/components/builder/guardrail-fields";
import { ToolPicker } from "@/components/builder/tool-picker";
import { knowledgeApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { toolName } from "@/lib/builder/graph";
import type { AgentConfig, ApprovalPolicy, DraftAgent } from "@/lib/builder/types";

const DEFAULT_APPROVALS: ApprovalPolicy = { read: false, edit: true, delete: true };

export type AgentSection = "identity" | "model" | "answers" | "tools" | "knowledge" | "approvals" | "guardrails";
export const ALL_SECTIONS: AgentSection[] = ["identity", "model", "answers", "tools", "knowledge", "approvals", "guardrails"];

/** Everything an owner sets on an agent. Works on a saved agent or a draft.
 *  ``only`` shows some sections (the node popup's accordion and wizard);
 *  ``stepOverride`` hides what a workflow step can't override (provider and model name). */
export function AgentFields({
  value,
  onChange,
  token,
  readOnly = false,
  only = ALL_SECTIONS,
  stepOverride = false,
}: {
  value: DraftAgent;
  onChange: (next: DraftAgent) => void;
  token: string;
  readOnly?: boolean;
  only?: AgentSection[];
  stepOverride?: boolean;
}) {
  const show = (section: AgentSection) => only.includes(section);
  const [adding, setAdding] = useState(false);
  const config: AgentConfig = value.config ?? {};
  const toolIds = config.tool_ids ?? [];
  const kbIds = config.knowledge_base_ids ?? [];
  const approvals = { ...DEFAULT_APPROVALS, ...(config.approvals ?? {}) };

  const set = (patch: Partial<DraftAgent>) => onChange({ ...value, ...patch });
  const setConfig = (patch: Partial<AgentConfig>) => set({ config: { ...config, ...patch } });

  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });

  const improve = useMutation({
    mutationFn: ({ field, text }: { field: "goal" | "instructions"; text: string }) =>
      builderApi.improveText(token, field, text, `Agent "${value.name}", role: ${value.role}`),
    onSuccess: (res, vars) => set({ [vars.field]: res.text } as Partial<DraftAgent>),
  });

  const ImproveButton = ({ field }: { field: "goal" | "instructions" }) =>
    readOnly ? null : (
      <button
        type="button"
        disabled={improve.isPending || !(value[field] ?? "").trim()}
        onClick={() => improve.mutate({ field, text: value[field] ?? "" })}
        className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-40 cursor-pointer"
      >
        {improve.isPending && improve.variables?.field === field ? <Spinner className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}
        Improve
      </button>
    );

  return (
    <fieldset disabled={readOnly} className="contents">
      {show("identity") && <Section title="Identity">
        <Field label="Name">
          <Input className="h-9" value={value.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="Role">
          <Input className="h-9" value={value.role} onChange={(e) => set({ role: e.target.value })} />
        </Field>
        <Field label="Goal" hint="What it does every time it runs.">
          <Textarea rows={2} value={value.goal} onChange={(e) => set({ goal: e.target.value })} />
          <ImproveButton field="goal" />
        </Field>
        <Field label="Instructions" hint="Expertise, tone, and what it must never do.">
          <Textarea rows={4} value={value.instructions ?? ""} onChange={(e) => set({ instructions: e.target.value })} />
          <ImproveButton field="instructions" />
        </Field>
        {improve.isError && <p className="text-xs text-red-600">Couldn&apos;t improve the text right now.</p>}
      </Section>}

      {show("model") && <Section title="Model">
        {!stepOverride && <div className="grid grid-cols-2 gap-2">
          <Field label="Provider">
            <Select value={value.llm_provider ?? ""} onChange={(e) => set({ llm_provider: e.target.value })}>
              <option value="">Default</option>
              <option value="azure">Azure OpenAI</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="groq">Groq</option>
            </Select>
          </Field>
          <Field label="Model">
            <Input className="h-9" placeholder="Provider default" value={value.llm_model ?? ""} onChange={(e) => set({ llm_model: e.target.value })} />
          </Field>
        </div>}
        <Field label="Temperature" hint="Lower = more predictable.">
          <Input
            className="h-9"
            type="number"
            step={0.1}
            min={0}
            max={2}
            value={config.llm?.temperature ?? ""}
            placeholder="0.3"
            onChange={(e) =>
              setConfig({ llm: { ...(config.llm ?? {}), temperature: e.target.value === "" ? null : Number(e.target.value) } })
            }
          />
        </Field>
        <Field label="Longest answer (tokens)" hint="Empty = the model's default.">
          <Input
            className="h-9"
            type="number"
            min={64}
            max={32000}
            placeholder="Default"
            value={config.llm?.max_output_tokens ?? ""}
            onChange={(e) => setConfig({ llm: { ...(config.llm ?? {}), max_output_tokens: e.target.value === "" ? null : Number(e.target.value) } })}
          />
        </Field>
        <Field label="Retries if the model fails">
          <Select value={config.reliability?.retries ?? 0} onChange={(e) => setConfig({ reliability: { ...(config.reliability ?? {}), retries: Number(e.target.value) } })}>
            {[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n === 0 ? "Don't retry" : `${n} ${n === 1 ? "time" : "times"}`}</option>)}
          </Select>
        </Field>
      </Section>}

      {show("answers") && <Section title="How it answers">
        <Field label="Tone" hint="professional, friendly, concise, technical — or your own words.">
          <Input className="h-9" value={config.response?.tone ?? ""} placeholder="Default" onChange={(e) => setConfig({ response: { ...(config.response ?? {}), tone: e.target.value } })} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Length">
            <Select value={config.response?.verbosity ?? "balanced"} onChange={(e) => setConfig({ response: { ...(config.response ?? {}), verbosity: e.target.value } })}>
              <option value="concise">Short</option>
              <option value="balanced">Balanced</option>
              <option value="detailed">Detailed</option>
            </Select>
          </Field>
          <Field label="Citations">
            <Select value={config.response?.citations ?? "always"} onChange={(e) => setConfig({ response: { ...(config.response ?? {}), citations: e.target.value } })}>
              <option value="always">Always</option>
              <option value="when_used">When it used a source</option>
              <option value="off">Off</option>
            </Select>
          </Field>
        </div>
        <Field label="Language" hint="auto = the language of the question.">
          <Input className="h-9" value={config.response?.language ?? "auto"} onChange={(e) => setConfig({ response: { ...(config.response ?? {}), language: e.target.value || "auto" } })} />
        </Field>
      </Section>}

      {show("tools") && <Section
        title={`Tools (${toolIds.length})`}
        action={
          !readOnly && (
            <button type="button" onClick={() => setAdding((a) => !a)} className="text-xs font-medium text-indigo-600 cursor-pointer">
              {adding ? "Done" : <span className="inline-flex items-center gap-0.5"><Plus className="h-3 w-3" /> Add</span>}
            </button>
          )
        }
      >
        {toolIds.length === 0 && <p className="text-xs text-zinc-400">No tools: it answers from what it&apos;s told and its knowledge.</p>}
        <ul className="flex flex-wrap gap-1.5">
          {toolIds.map((id) => (
            <li key={id} className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800">
              {toolName(id)}
              {!readOnly && (
                <button type="button" aria-label={`Remove ${toolName(id)}`} onClick={() => setConfig({ tool_ids: toolIds.filter((t) => t !== id) })} className="cursor-pointer">
                  <X className="h-3 w-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
        {adding && (
          <ToolPicker token={token} exclude={toolIds} onPick={(t) => setConfig({ tool_ids: [...toolIds, t.tool_id] })} />
        )}
        <Field label="Most tool calls per run">
          <Input
            className="h-9"
            type="number"
            min={1}
            max={20}
            value={config.tools?.max_calls ?? 8}
            onChange={(e) => setConfig({ tools: { ...(config.tools ?? {}), max_calls: Number(e.target.value) || 8 } })}
          />
        </Field>
      </Section>}

      {show("knowledge") && <Section title="Knowledge">
        {kbs.isLoading ? (
          <Spinner className="h-4 w-4 text-zinc-400" />
        ) : (kbs.data ?? []).length === 0 ? (
          <p className="text-xs text-zinc-400">No knowledge bases yet — create one under Knowledge Base.</p>
        ) : (
          <div className="space-y-1.5">
            {(kbs.data ?? []).map((kb) => (
              <Toggle
                key={kb.id}
                label={kb.name}
                checked={kbIds.includes(kb.id)}
                onChange={(on) => setConfig({ knowledge_base_ids: on ? [...kbIds, kb.id] : kbIds.filter((k) => k !== kb.id) })}
              />
            ))}
          </div>
        )}
      </Section>}

      {show("approvals") && <Section title="Ask me before it runs">
        <Toggle label="Tools that only read" checked={approvals.read} onChange={(v) => setConfig({ approvals: { ...approvals, read: v } })} />
        <Toggle label="Tools that change data" checked={approvals.edit} onChange={(v) => setConfig({ approvals: { ...approvals, edit: v } })} />
        <Toggle label="Tools that delete" checked={approvals.delete} onChange={(v) => setConfig({ approvals: { ...approvals, delete: v } })} />
      </Section>}

      {show("guardrails") && <GuardrailFields
        agent={value}
        value={config.guardrails ?? {}}
        hasKnowledge={kbIds.length > 0}
        token={token}
        readOnly={readOnly}
        onChange={(guardrails) => setConfig({ guardrails })}
      />}
    </fieldset>
  );
}
