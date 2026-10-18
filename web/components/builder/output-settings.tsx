"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Braces, Eye, FileText, LayoutList, MessageSquareText, Plus, Trash2 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Section, Textarea, Toggle } from "@/components/builder/fields";
import { AnswerView } from "@/components/builder/run-output";
import { builderApi } from "@/lib/builder/api";
import type { OutputConfig } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

const FORMATS: { id: string; label: string; hint: string; Icon: typeof FileText }[] = [
  { id: "markdown", label: "As written", hint: "The steps' answer, merged if several", Icon: FileText },
  { id: "formatted", label: "Report", hint: "Re-laid out under headings you pick", Icon: LayoutList },
  { id: "text", label: "Plain text", hint: "No markdown — SMS, WhatsApp, email", Icon: MessageSquareText },
  { id: "json", label: "JSON", hint: "One object — for apps and integrations", Icon: Braces },
];

const PRESETS: { id: string; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "key_points", label: "Key points" },
  { id: "details", label: "Details" },
  { id: "next_steps", label: "Next steps (only if there's something to do)" },
];

/** Ready-made custom layouts: one click fills the section list. */
const LAYOUTS: { label: string; sections: { title: string; hint: string }[] }[] = [
  {
    label: "Lead report",
    sections: [
      { title: "Summary", hint: "What was searched, how many companies were found and qualified, and which sources produced them." },
      { title: "Ranked leads", hint: "One table: rank, company, country, industry, employees, fit score, main signal, date, source." },
      { title: "Lead details", hint: "Per qualified company: profile, evidence table with quotes and URLs, why now, contacts, people, suggested angle." },
      { title: "Not qualified", hint: "A table: company and the reason." },
      { title: "Sources used", hint: "Each source and how many findings it gave." },
    ],
  },
  {
    label: "Executive brief",
    sections: [
      { title: "Bottom line", hint: "The answer in 2 sentences." },
      { title: "What we found", hint: "3-6 bullets with the most important facts." },
      { title: "Recommended actions", hint: "Numbered, concrete, with an owner if the answer names one." },
    ],
  },
];

/**
 * An output step's settings (backend builder/graph/output_config.py): how the run's final answer is
 * shaped — format, the report's headings (preset or your own), instructions in words, language,
 * header/footer — with a preview on the last run's texts, so a change is seen without running again.
 */
export function OutputSettings({
  config,
  incoming,
  token,
  workflowId,
  nodeId,
  lastRunId,
  onChange,
}: {
  config: OutputConfig | null | undefined;
  /** How many lines lead into the step (merging only matters with 2+). */
  incoming: number;
  token: string;
  workflowId: string;
  nodeId: string;
  lastRunId?: string | null;
  onChange: (next: OutputConfig) => void;
}) {
  const oc: OutputConfig = config ?? {};
  const fmt = oc.format ?? "markdown";
  const custom = oc.custom_sections ?? [];
  const [layout, setLayout] = useState<"preset" | "custom">(custom.length ? "custom" : "preset");
  const set = (patch: Partial<OutputConfig>) => onChange({ ...oc, ...patch });
  const setCustom = (list: { title: string; hint?: string }[]) => set({ custom_sections: list });
  const presets = oc.sections ?? PRESETS.map((p) => p.id);

  const preview = useMutation({
    mutationFn: () => builderApi.outputPreview(token, workflowId, { run_id: lastRunId!, node_id: nodeId, output_config: oc }),
  });

  return (
    <>
      <Section title="Answer format">
        <div className="grid grid-cols-2 gap-1.5">
          {FORMATS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={fmt === f.id}
              onClick={() => set({ format: f.id })}
              className={cn(
                "rounded-lg border p-2 text-left transition-colors cursor-pointer",
                fmt === f.id ? "border-emerald-500 bg-emerald-50 ring-1 ring-emerald-500" : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
              )}
            >
              <span className="flex items-center gap-1.5 text-xs font-semibold text-zinc-900">
                <f.Icon className={cn("h-3.5 w-3.5", fmt === f.id ? "text-emerald-600" : "text-zinc-400")} /> {f.label}
              </span>
              <span className="mt-0.5 block text-[10.5px] leading-snug text-zinc-500">{f.hint}</span>
            </button>
          ))}
        </div>
      </Section>

      {fmt === "formatted" && (
        <Section title="Report layout">
          <Field label="Title" hint="Empty = a title from the answer. {{date}} becomes today's date.">
            <Input className="h-9" placeholder="e.g. Lead research – {{date}}" value={oc.title ?? ""} onChange={(e) => set({ title: e.target.value })} />
          </Field>
          <div className="inline-flex rounded-lg border border-zinc-200 p-0.5 text-xs">
            {(["preset", "custom"] as const).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => {
                  setLayout(l);
                  if (l === "preset") set({ custom_sections: [] });
                }}
                className={cn("rounded-md px-2.5 py-1 font-medium cursor-pointer", layout === l ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900")}
              >
                {l === "preset" ? "Standard sections" : "My own sections"}
              </button>
            ))}
          </div>
          {layout === "preset" ? (
            <div className="space-y-1.5">
              {PRESETS.map((p) => (
                <Toggle
                  key={p.id}
                  label={p.label}
                  checked={presets.includes(p.id)}
                  onChange={(on) => set({ sections: on ? PRESETS.map((x) => x.id).filter((x) => x === p.id || presets.includes(x)) : presets.filter((x) => x !== p.id) })}
                />
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1">
                {LAYOUTS.map((l) => (
                  <button key={l.label} type="button" onClick={() => setCustom(l.sections)} className="rounded-full border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 hover:border-emerald-400 hover:text-emerald-700 cursor-pointer">
                    Use “{l.label}”
                  </button>
                ))}
              </div>
              {custom.map((c, i) => (
                <div key={i} className="rounded-lg border border-zinc-200 p-2">
                  <div className="flex items-center gap-1">
                    <span className="w-5 text-center text-[11px] font-semibold text-zinc-400">{i + 1}</span>
                    <Input
                      className="h-8 flex-1 text-xs"
                      placeholder="Heading"
                      value={c.title}
                      onChange={(e) => setCustom(custom.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
                    />
                    <button type="button" aria-label="Move up" disabled={i === 0} onClick={() => setCustom(swap(custom, i, i - 1))} className="rounded p-1 text-zinc-400 hover:text-zinc-700 disabled:opacity-30 cursor-pointer"><ArrowUp className="h-3.5 w-3.5" /></button>
                    <button type="button" aria-label="Move down" disabled={i === custom.length - 1} onClick={() => setCustom(swap(custom, i, i + 1))} className="rounded p-1 text-zinc-400 hover:text-zinc-700 disabled:opacity-30 cursor-pointer"><ArrowDown className="h-3.5 w-3.5" /></button>
                    <button type="button" aria-label="Remove section" onClick={() => setCustom(custom.filter((_, j) => j !== i))} className="rounded p-1 text-zinc-400 hover:text-red-600 cursor-pointer"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                  <Textarea
                    rows={2}
                    className="mt-1.5 text-xs"
                    placeholder="What goes in it, e.g. one table: company, score, source"
                    value={c.hint ?? ""}
                    onChange={(e) => setCustom(custom.map((x, j) => (j === i ? { ...x, hint: e.target.value } : x)))}
                  />
                </div>
              ))}
              {custom.length < 12 && (
                <button type="button" onClick={() => setCustom([...custom, { title: "", hint: "" }])} className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 cursor-pointer">
                  <Plus className="h-3.5 w-3.5" /> Add a section
                </button>
              )}
            </div>
          )}
        </Section>
      )}

      <Section title="Shape it in your words">
        <Field label="Instructions" hint="Followed when the answer is shaped. Never adds facts — only lays out what the steps found.">
          <Textarea
            rows={3}
            placeholder={fmt === "json" ? "e.g. {leads: [{company, country, score, source_url}]}" : "e.g. Best leads first, at most 10. Keep every URL. Bold the company names."}
            value={oc.instructions ?? ""}
            onChange={(e) => set({ instructions: e.target.value })}
          />
        </Field>
        {(fmt === "markdown" || fmt === "text") && incoming > 1 && (
          <Toggle label="Merge the incoming answers into one" checked={(oc.compose ?? "auto") === "auto"} onChange={(on) => set({ compose: on ? "auto" : "off" })} />
        )}
        <Field label="Language" hint="Empty = the same language as the answer.">
          <Input className="h-9" placeholder="e.g. Hindi" value={oc.language ?? ""} onChange={(e) => set({ language: e.target.value || null })} />
        </Field>
        {fmt !== "json" && (
          <>
            <Field label="Header" hint="Added above the answer as written. {{date}} = today.">
              <Textarea rows={2} value={oc.header ?? ""} onChange={(e) => set({ header: e.target.value })} />
            </Field>
            <Field label="Footer">
              <Textarea rows={2} value={oc.footer ?? ""} onChange={(e) => set({ footer: e.target.value })} />
            </Field>
          </>
        )}
      </Section>

      <Section title="Preview">
        <p className="text-[11px] text-zinc-500">
          These settings on what reached this step in the last run — nothing else runs again (one AI call for Report, JSON or instructions).
        </p>
        <button
          type="button"
          disabled={!lastRunId || preview.isPending}
          onClick={() => preview.mutate()}
          className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 cursor-pointer"
        >
          {preview.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />} {lastRunId ? "Preview on the last run" : "Run the workflow once to preview"}
        </button>
        {preview.error && <p className="text-xs text-red-600">{preview.error instanceof Error ? preview.error.message : "Couldn't preview."}</p>}
        {preview.data && (
          <div className="max-h-80 overflow-y-auto rounded-lg border border-zinc-200 p-2.5 text-sm text-zinc-900">
            <AnswerView text={preview.data.text} />
          </div>
        )}
      </Section>
    </>
  );
}

function swap<T>(list: T[], a: number, b: number): T[] {
  const out = [...list];
  [out[a], out[b]] = [out[b], out[a]];
  return out;
}
