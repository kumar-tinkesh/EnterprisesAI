"use client";

import { AlertTriangle, BookOpen, Bot, Gauge, Hand, Link2, MessageSquare, ShieldCheck, Target, Wrench, XCircle, type LucideIcon } from "lucide-react";

import type { StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { askFirstFor, groupByServer, guardrailsOn, matchingProfile, toolList, type Issue, type WizardStepId } from "@/lib/builder/agent-wizard";
import { cn } from "@/lib/utils";

/** Step six: everything above in plain words, what still needs you, then Create. */
export function ReviewStep({
  draft,
  servers,
  profiles,
  goTo,
  connect,
  issues,
  kbNames,
  createError,
}: StepProps & { issues: Issue[]; kbNames: Record<string, string>; createError: string[] }) {
  const config = draft.config;
  const groups = groupByServer(config.tool_ids ?? []);
  const kbs = (config.knowledge_base_ids ?? []).map((id) => kbNames[id] ?? "Knowledge base");
  const checks = guardrailsOn(config.guardrails);
  const askFirst = askFirstFor(config.approvals);
  const profile = matchingProfile(config, profiles);
  const r = config.response ?? {};
  const replies = [r.tone || null, r.verbosity && r.verbosity !== "balanced" ? `${r.verbosity === "concise" ? "short" : "detailed"} answers` : null, r.language && r.language !== "auto" ? `in ${r.language}` : null]
    .filter(Boolean)
    .join(", ");
  const blocking = issues.filter((i) => i.level === "block");
  const warnings = issues.filter((i) => i.level === "warn");

  const rows: { icon: LucideIcon; label: string; step: WizardStepId; value: React.ReactNode }[] = [
    { icon: Bot, label: "Agent", step: "identity", value: <><strong className="text-zinc-900">{draft.name || "Unnamed"}</strong>{draft.role && ` — ${draft.role}`}</> },
    { icon: Target, label: "Goal", step: "identity", value: draft.goal || <em className="text-zinc-400">Not set</em> },
    {
      icon: Wrench,
      label: "Tools",
      step: "abilities",
      value: groups.length ? (
        <ul className="space-y-0.5">
          {groups.map((g) => {
            const s = servers[g.serverId];
            return (
              <li key={g.serverId}>
                <span className="font-medium text-zinc-900">{s?.name ?? "App"}</span>: {toolList(g.toolIds)}
                {s && !s.connected && !s.loading && <span className="text-amber-700"> (not connected)</span>}
              </li>
            );
          })}
        </ul>
      ) : "None — it works from what it's asked",
    },
    { icon: BookOpen, label: "Documents", step: "abilities", value: kbs.length ? kbs.join(", ") : "None" },
    { icon: ShieldCheck, label: "Safety", step: "behaviour", value: checks.length ? checks.join("; ") : "No extra checks" },
    { icon: Hand, label: "Asks you first before", step: "behaviour", value: askFirst.length ? askFirst.join(", ") : "Never — it acts on its own" },
    { icon: MessageSquare, label: "Replies", step: "behaviour", value: replies || "Balanced length, in the language it's asked in" },
    {
      icon: Gauge,
      label: "Engine",
      step: "engine",
      value: `${profile?.label ?? "Custom"} · ${draft.llm_model || "default model"} · up to ${config.tools?.max_calls ?? 8} tool calls`,
    },
  ];

  const flow = [
    { t: "Gets your request", d: "Anything you send it, in plain language." },
    ...(kbs.length ? [{ t: "Searches its documents", d: kbs.join(", ") }] : []),
    ...(groups.length
      ? [{ t: "Uses its tools", d: askFirst.length ? `Stops to ask you before ${askFirst.join(" or ")}.` : "Without stopping to ask." }]
      : []),
    { t: "Answers", d: checks.length ? `After its safety checks (${checks.length}).` : "Straight away." },
  ];

  return (
    <div className="space-y-4">
      {(blocking.length > 0 || warnings.length > 0) && (
        <div className="space-y-2">
          {[...blocking, ...warnings].map((i, n) => (
            <div
              key={n}
              className={cn("flex flex-wrap items-start gap-2 rounded-lg border p-2.5 text-xs", i.level === "block" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-900")}
            >
              {i.level === "block" ? <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
              <span className="min-w-0 flex-1">{i.message}</span>
              {i.serverId ? (
                <button type="button" onClick={() => connect(i.serverId!)} className="inline-flex items-center gap-1 font-semibold underline cursor-pointer">
                  <Link2 className="h-3 w-3" /> Connect
                </button>
              ) : (
                <button type="button" onClick={() => goTo(i.step)} className="font-semibold underline cursor-pointer">Fix</button>
              )}
            </div>
          ))}
        </div>
      )}

      <section className="rounded-xl border border-zinc-200 bg-white" aria-label="Summary">
        <dl className="divide-y divide-zinc-100">
          {rows.map((row) => (
            <div key={row.label} className="flex gap-3 p-3">
              <row.icon className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
              <div className="min-w-0 flex-1">
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">{row.label}</dt>
                <dd className="mt-0.5 break-words text-xs leading-relaxed text-zinc-700">{row.value}</dd>
              </div>
              <button type="button" onClick={() => goTo(row.step)} className="self-start text-[11px] font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer">
                Edit
              </button>
            </div>
          ))}
        </dl>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-3" aria-label="How a run goes">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Every time it runs</h3>
        <ol className="space-y-2">
          {flow.map((f, i) => (
            <li key={f.t} className="flex gap-3">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-[10px] font-semibold text-indigo-700">{i + 1}</span>
              <span className="min-w-0">
                <span className="block text-xs font-medium text-zinc-900">{f.t}</span>
                <span className="block break-words text-[11px] text-zinc-500">{f.d}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      {createError.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800" role="alert">
          <p className="font-semibold">It couldn&apos;t be created</p>
          {createError.map((e, i) => <p key={i}>• {e}</p>)}
        </div>
      )}
    </div>
  );
}
