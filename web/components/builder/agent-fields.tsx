"use client";

import { useContext, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Plus, Sparkles, Unplug, X } from "lucide-react";

import { ConnectButton, useMissingServers } from "@/components/connections/connect-button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { BoolParam, Field, OverrideParams, Pair, Param, Section, Select, Textarea, Toggle } from "@/components/builder/fields";
import { GuardrailFields } from "@/components/builder/guardrail-fields";
import { ToolPicker } from "@/components/builder/tool-picker";
import { NeedsSection } from "@/components/builder/tool-needs";
import { knowledgeApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { toolName } from "@/lib/builder/graph";
import type { AgentConfig, ApprovalPolicy, DraftAgent } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

const DEFAULT_APPROVALS: ApprovalPolicy = { read: false, edit: true, delete: true };

export type AgentSection = "identity" | "model" | "answers" | "tools" | "limits" | "knowledge" | "memory" | "approvals" | "guardrails";
export const ALL_SECTIONS: AgentSection[] = ["identity", "model", "answers", "tools", "limits", "knowledge", "memory", "approvals", "guardrails"];

const FORMATS: [string, string][] = [["markdown", "Markdown"], ["tables", "Tables"], ["code", "Code blocks"], ["bullets", "Bullet points"]];
const RETRY_ON: [string, string][] = [["rate_limit", "Rate limits"], ["timeout", "Timeouts"], ["server", "Server errors"], ["provider", "Provider errors"]];

/** Chips that toggle values in a list. */
function Chips({ options, value, onChange }: { options: [string, string][]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map(([id, label]) => {
        const on = value.includes(id);
        return (
          <button
            key={id}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((v) => v !== id) : [...value, id])}
            className={cn("rounded-full border px-2.5 py-1 text-xs font-medium cursor-pointer", on ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-zinc-200 text-zinc-500 hover:text-zinc-800")}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

/** A comma-separated list, kept as typed and read when the field is left. */
function ListInput({ value, max, onChange }: { value: string[]; max: number; onChange: (v: string[]) => void }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <Input
      className="h-9"
      placeholder="None"
      value={text ?? value.join(", ")}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (text === null) return;
        onChange(text.split(",").map((t) => t.trim()).filter(Boolean).slice(0, max));
        setText(null);
      }}
    />
  );
}

/** Everything an owner sets on an agent. Works on a saved agent or a draft.
 *  ``only`` shows some sections (the node popup's accordion and wizard);
 *  ``stepOverride``: the fields are a workflow step's own values (the model falls back to the agent's). */
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
  // As a step's overrides: a setting is editable only while switched on.
  const params = useContext(OverrideParams);
  const editable = (k: string) => !params || params.isOn(k);
  const [adding, setAdding] = useState(false);
  const config: AgentConfig = value.config ?? {};
  const toolIds = config.tool_ids ?? [];
  const kbIds = config.knowledge_base_ids ?? [];
  const approvals = { ...DEFAULT_APPROVALS, ...(config.approvals ?? {}) };

  const set = (patch: Partial<DraftAgent>) => onChange({ ...value, ...patch });
  const setConfig = (patch: Partial<AgentConfig>) => set({ config: { ...config, ...patch } });

  // Tools of systems this user hasn't connected (connections are each person's own).
  const missing = useMissingServers(token, toolIds);
  const offline = new Set(missing.flatMap((m) => m.tools));
  const removed = new Set(missing.filter((m) => m.removed).flatMap((m) => m.tools));

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
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-40 cursor-pointer"
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
        <Pair>
          <Param k="llm_provider" label="Provider">
            <Select value={value.llm_provider ?? ""} onChange={(e) => set({ llm_provider: e.target.value })}>
              <option value="">Default</option>
              <option value="azure">Azure OpenAI</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="groq">Groq</option>
            </Select>
          </Param>
          <Param k="llm_model" label="Model">
            <Input className="h-9" placeholder={stepOverride ? "The agent's model" : "Provider default"} value={value.llm_model ?? ""} onChange={(e) => set({ llm_model: e.target.value })} />
          </Param>
        </Pair>
        <Param k="llm.temperature" label="Temperature" hint="Lower = more predictable.">
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
        </Param>
        <Param k="llm.max_output_tokens" label="Longest answer (tokens)" hint="Empty = the model's default.">
          <Input
            className="h-9"
            type="number"
            min={64}
            max={32000}
            placeholder="Default"
            value={config.llm?.max_output_tokens ?? ""}
            onChange={(e) => setConfig({ llm: { ...(config.llm ?? {}), max_output_tokens: e.target.value === "" ? null : Number(e.target.value) } })}
          />
        </Param>
        <Param k="llm.reasoning_effort" label="Thinking effort" hint="For models that reason (gpt-5, o-series, Gemini 2.5). Higher = more careful, slower.">
          <Select value={config.llm?.reasoning_effort ?? "auto"} onChange={(e) => setConfig({ llm: { ...(config.llm ?? {}), reasoning_effort: e.target.value } })}>
            <option value="auto">Auto</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </Select>
        </Param>
        <Pair>
          <Param k="reliability.retries" label="Retries if the model fails">
            <Select value={config.reliability?.retries ?? 0} onChange={(e) => setConfig({ reliability: { ...(config.reliability ?? {}), retries: Number(e.target.value) } })}>
              {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n === 0 ? "Don't retry" : `${n} ${n === 1 ? "time" : "times"}`}</option>)}
            </Select>
          </Param>
          <Param k="reliability.request_timeout_seconds" label="Wait for the model (s)">
            <Input
              className="h-9"
              type="number"
              min={10}
              max={600}
              placeholder="300"
              value={config.reliability?.request_timeout_seconds ?? ""}
              onChange={(e) => setConfig({ reliability: { ...(config.reliability ?? {}), request_timeout_seconds: e.target.value === "" ? null : Math.min(600, Math.max(10, Number(e.target.value))) } })}
            />
          </Param>
        </Pair>
        {(config.reliability?.retries ?? 0) > 0 && (
          <Param k="reliability.retry_on" label="Retry on">
            <Chips
              options={RETRY_ON}
              value={config.reliability?.retry_on ?? ["rate_limit", "timeout", "server", "provider"]}
              onChange={(retry_on) => setConfig({ reliability: { ...(config.reliability ?? {}), retry_on } })}
            />
          </Param>
        )}
        <Param k="reliability.fallback_model" label="Fallback model" hint="Answers if its own model still fails. Empty = none.">
          <Input className="h-9" placeholder="e.g. gpt-4o-mini" value={config.reliability?.fallback_model ?? ""} onChange={(e) => setConfig({ reliability: { ...(config.reliability ?? {}), fallback_model: e.target.value.trim() } })} />
        </Param>
        <Param k="llm.stop_sequences" label="Stop at" hint="Up to 4 texts, comma-separated: it stops writing when it would write one.">
          <ListInput value={config.llm?.stop_sequences ?? []} max={4} onChange={(stop_sequences) => setConfig({ llm: { ...(config.llm ?? {}), stop_sequences } })} />
        </Param>
      </Section>}

      {show("answers") && <Section title="How it answers">
        <Param k="response.tone" label="Tone" hint="professional, friendly, concise, technical — or your own words.">
          <Input className="h-9" value={config.response?.tone ?? ""} placeholder="Default" onChange={(e) => setConfig({ response: { ...(config.response ?? {}), tone: e.target.value } })} />
        </Param>
        <Pair>
          <Param k="response.verbosity" label="Length">
            <Select value={config.response?.verbosity ?? "balanced"} onChange={(e) => setConfig({ response: { ...(config.response ?? {}), verbosity: e.target.value } })}>
              <option value="concise">Short</option>
              <option value="balanced">Balanced</option>
              <option value="detailed">Detailed</option>
            </Select>
          </Param>
          <Param k="response.citations" label="Citations">
            <Select value={config.response?.citations ?? "always"} onChange={(e) => setConfig({ response: { ...(config.response ?? {}), citations: e.target.value } })}>
              <option value="always">Always</option>
              <option value="when_used">When it used a source</option>
              <option value="off">Off</option>
            </Select>
          </Param>
        </Pair>
        <Param k="response.language" label="Language" hint="auto = the language of the question.">
          <Input className="h-9" value={config.response?.language ?? "auto"} onChange={(e) => setConfig({ response: { ...(config.response ?? {}), language: e.target.value || "auto" } })} />
        </Param>
        <Param k="response.formats" label="Formatting" hint="None picked = whatever suits the answer.">
          <Chips options={FORMATS} value={config.response?.formats ?? []} onChange={(formats) => setConfig({ response: { ...(config.response ?? {}), formats } })} />
        </Param>
      </Section>}

      {show("tools") && <Section
        title={`Tools (${toolIds.length})`}
        action={
          !readOnly && editable("tool_ids") && (
            <button type="button" onClick={() => setAdding((a) => !a)} className="text-xs font-medium text-indigo-600 cursor-pointer">
              {adding ? "Done" : <span className="inline-flex items-center gap-0.5"><Plus className="h-3 w-3" /> Add</span>}
            </button>
          )
        }
      >
        <Param k="tool_ids" label="Its tools">
        {toolIds.length === 0 && <p className="text-xs text-zinc-400">No tools: it answers from what it&apos;s told and its knowledge.</p>}
        <ul className="flex flex-wrap gap-1.5">
          {toolIds.map((id) => (
            <li
              key={id}
              title={removed.has(id) ? "Its system was removed — this tool can't run" : offline.has(id) ? "Not connected for you yet — this tool won't run until you connect" : "Connected"}
              className={cn(
                "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs",
                removed.has(id) ? "bg-red-50 text-red-800 line-through ring-1 ring-red-300" : offline.has(id) ? "bg-amber-50 text-amber-800 ring-1 ring-amber-300" : "bg-emerald-50 text-emerald-800",
              )}
            >
              {offline.has(id) ? <Unplug className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
              {toolName(id)}
              {!readOnly && (
                <button type="button" aria-label={`Remove ${toolName(id)}`} onClick={() => setConfig({ tool_ids: toolIds.filter((t) => t !== id) })} className="cursor-pointer">
                  <X className="h-3 w-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
        {missing.map((m) => (
          m.removed ? (
            <div key={m.serverId} className="mt-2 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5">
              <p className="min-w-0 flex-1 text-xs text-red-800">
                {m.tools.length === 1 ? "A tool" : `${m.tools.length} tools`} belong to a system that was removed or isn&apos;t available to you — remove {m.tools.length === 1 ? "it" : "them"} and add the new system&apos;s tools.
              </p>
              {!readOnly && editable("tool_ids") && (
                <button type="button" onClick={() => setConfig({ tool_ids: toolIds.filter((t) => !m.tools.includes(t)) })} className="shrink-0 rounded-md border border-red-300 px-2 py-0.5 text-xs font-medium text-red-700 hover:bg-red-100 cursor-pointer">
                  Remove
                </button>
              )}
            </div>
          ) : (
            <div key={m.serverId} className="mt-2 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5">
              <p className="min-w-0 flex-1 text-xs text-amber-800">
                <span className="font-semibold">{m.name}</span> isn&apos;t connected for you — {m.tools.length === 1 ? "its tool" : `its ${m.tools.length} tools`} won&apos;t run.
              </p>
              <ConnectButton serverId={m.serverId} token={token} className="px-2 py-0.5 text-xs" />
            </div>
          )
        ))}
        {adding && (
          <ToolPicker token={token} exclude={toolIds} onPick={(t) => setConfig({ tool_ids: [...toolIds, t.tool_id] })} />
        )}
        </Param>
        {(config.tool_needs ?? []).length > 0 && <NeedsSection token={token} needs={config.tool_needs ?? []} />}
      </Section>}

      {show("limits") && <Section title="Tool limits">
        <Pair>
          <Param k="tools.max_calls" label="Most tool calls per run">
            <Input
              className="h-9"
              type="number"
              min={1}
              max={20}
              value={config.tools?.max_calls ?? 8}
              onChange={(e) => setConfig({ tools: { ...(config.tools ?? {}), max_calls: Math.min(20, Math.max(1, Number(e.target.value) || 8)) } })}
            />
          </Param>
          <Param k="tools.timeout_seconds" label="Wait for a tool (s)">
            <Input
              className="h-9"
              type="number"
              min={5}
              max={300}
              value={config.tools?.timeout_seconds ?? 30}
              onChange={(e) => setConfig({ tools: { ...(config.tools ?? {}), timeout_seconds: Math.min(300, Math.max(5, Number(e.target.value) || 30)) } })}
            />
          </Param>
        </Pair>
        <Param k="tools.on_failure" label="When a tool fails">
          <Select value={config.tools?.on_failure ?? "continue"} onChange={(e) => setConfig({ tools: { ...(config.tools ?? {}), on_failure: e.target.value } })}>
            <option value="continue">Tell the agent and carry on</option>
            <option value="retry">Try twice more, then carry on</option>
            <option value="stop">Stop the run</option>
          </Select>
        </Param>
      </Section>}

      {show("knowledge") && <Section title="Knowledge">
        <Param k="knowledge_base_ids" label="Knowledge bases">
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
        </Param>
      </Section>}

      {show("memory") && <Section title="Memory">
        <BoolParam
          k="memory.enabled"
          label="Remember things about the people it works for"
          checked={!!config.memory?.enabled}
          onChange={(enabled) => setConfig({ memory: { max_items: 50, ...(config.memory ?? {}), enabled } })}
        />
        {config.memory?.enabled && (
          <Param k="memory.max_items" label="Most facts kept per person" hint="The oldest go first.">
            <Input
              className="h-9"
              type="number"
              min={5}
              max={200}
              value={config.memory?.max_items ?? 50}
              onChange={(e) => setConfig({ memory: { ...(config.memory ?? {}), max_items: Math.min(200, Math.max(5, Number(e.target.value) || 50)) } })}
            />
          </Param>
        )}
      </Section>}

      {show("approvals") && <Section title="Ask me before it runs">
        <BoolParam k="approvals.read" label="Tools that only read" checked={approvals.read} onChange={(v) => setConfig({ approvals: { ...approvals, read: v } })} />
        <BoolParam k="approvals.edit" label="Tools that change data" checked={approvals.edit} onChange={(v) => setConfig({ approvals: { ...approvals, edit: v } })} />
        <BoolParam k="approvals.delete" label="Tools that delete" checked={approvals.delete} onChange={(v) => setConfig({ approvals: { ...approvals, delete: v } })} />
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
