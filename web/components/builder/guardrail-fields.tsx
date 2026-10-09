"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus, ShieldCheck, Sparkles, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Section, Select, Toggle } from "@/components/builder/fields";
import { builderApi } from "@/lib/builder/api";
import type { DraftAgent, GuardrailSettings } from "@/lib/builder/types";

/** The agent's guardrails: what's checked around every run, and what happens when one trips. */
export function GuardrailFields({
  agent,
  value,
  hasKnowledge,
  token,
  readOnly,
  onChange,
}: {
  agent: DraftAgent;
  value: GuardrailSettings;
  hasKnowledge: boolean;
  token: string;
  readOnly?: boolean;
  onChange: (next: GuardrailSettings) => void;
}) {
  const [rule, setRule] = useState("");
  const [reasoning, setReasoning] = useState<string | null>(null);
  const rules = value.custom_rules ?? [];
  const set = (patch: Partial<GuardrailSettings>) => onChange({ ...value, ...patch });
  const addRule = () => {
    const r = rule.trim();
    if (r && !rules.includes(r) && rules.length < 10) set({ custom_rules: [...rules, r] });
    setRule("");
  };
  const judged = rules.length > 0 || (value.groundedness && value.groundedness_mode === "llm");

  const suggest = useMutation({
    mutationFn: () =>
      builderApi.suggestGuardrails(token, {
        name: agent.name, role: agent.role, goal: agent.goal, instructions: agent.instructions ?? "",
        tool_ids: agent.config?.tool_ids ?? [], has_knowledge: hasKnowledge,
      }),
    onSuccess: (res) => {
      onChange({ ...value, ...res.guardrails, custom_rules: Array.from(new Set([...rules, ...(res.guardrails.custom_rules ?? [])])).slice(0, 10) });
      setReasoning(res.reasoning || "Suggested settings applied.");
    },
  });

  return (
    <Section
      title="Guardrails"
      action={
        !readOnly && (
          <button
            type="button"
            disabled={suggest.isPending || !agent.goal?.trim()}
            onClick={() => suggest.mutate()}
            className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-40 cursor-pointer"
          >
            {suggest.isPending ? <Spinner className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />} Suggest
          </button>
        )
      }
    >
      {reasoning && (
        <p className="flex gap-1.5 rounded-lg bg-indigo-50 p-2 text-xs text-indigo-900">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{reasoning} Review, then Save.</span>
        </p>
      )}
      {suggest.isError && <p className="text-xs text-red-600">{suggest.error instanceof Error ? suggest.error.message : "Couldn't suggest guardrails."}</p>}

      <Toggle label="Refuse requests that try to override its instructions" checked={!!value.injection} onChange={(v) => set({ injection: v })} />
      <Toggle label="Treat instructions inside tool results as data" checked={!!value.tool_injection} onChange={(v) => set({ tool_injection: v })} />
      <p className="-mt-1.5 pl-6 text-[11px] text-zinc-400">For tools that read emails, web pages or documents other people wrote.</p>
      <Toggle label="Hide personal data from the model" checked={!!value.pii_input} onChange={(v) => set({ pii_input: v })} />
      <Toggle label="Hide personal data in answers" checked={!!value.pii_output} onChange={(v) => set({ pii_output: v })} />
      <p className="-mt-1.5 pl-6 text-[11px] text-zinc-400">Emails, phone numbers, cards, Aadhaar, PAN, API keys.</p>

      <Toggle
        label="Check answers against its knowledge"
        checked={!!value.groundedness}
        onChange={(v) => set({ groundedness: v })}
      />
      {!hasKnowledge && value.groundedness && <p className="-mt-1.5 pl-6 text-[11px] text-amber-700">Pick a knowledge base above — there's nothing to check against yet.</p>}
      {value.groundedness && (
        <Select className="ml-6 w-[calc(100%-1.5rem)]" value={value.groundedness_mode ?? "fast"} onChange={(e) => set({ groundedness_mode: e.target.value as "fast" | "llm" })}>
          <option value="fast">Quick — catches answers that leave the documents</option>
          <option value="llm">Strict — checks every claim (one extra model call)</option>
        </Select>
      )}

      <Field label="Rules it must follow" hint="Told to the agent and checked on every answer (one extra model call).">
        <div className="space-y-1.5">
          {rules.map((r) => (
            <div key={r} className="flex items-start gap-1.5 rounded-md bg-zinc-50 px-2 py-1.5 text-xs text-zinc-800">
              <span className="flex-1">{r}</span>
              {!readOnly && (
                <button type="button" aria-label={`Remove rule: ${r}`} onClick={() => set({ custom_rules: rules.filter((x) => x !== r) })} className="text-zinc-400 hover:text-red-600 cursor-pointer">
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          ))}
          {!readOnly && rules.length < 10 && (
            <div className="flex gap-1.5">
              <Input
                className="h-8 text-xs"
                value={rule}
                maxLength={300}
                placeholder="e.g. Never quote a price that isn't in the price list"
                onChange={(e) => setRule(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addRule();
                  }
                }}
              />
              <button type="button" aria-label="Add rule" disabled={!rule.trim()} onClick={addRule} className="rounded-md border border-zinc-200 px-2 text-zinc-500 hover:text-indigo-600 disabled:opacity-40 cursor-pointer">
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      </Field>

      {judged && (
        <Field label="When a rule is broken or a claim isn't supported">
          <Select value={value.on_violation ?? "flag"} onChange={(e) => set({ on_violation: e.target.value as "flag" | "block" })}>
            <option value="flag">Show the answer with a warning</option>
            <option value="block">Withhold the answer</option>
          </Select>
        </Field>
      )}
    </Section>
  );
}
