"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Circle, Play, Radio, ShieldAlert, Square, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ApprovalCard } from "@/components/builder/approval-card";
import { Field, Select, Textarea } from "@/components/builder/fields";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { isFinished, type RunView } from "@/lib/builder/run-state";
import type { InputVariable, Problem, Run } from "@/lib/builder/types";
import { useRunStream } from "@/lib/builder/use-run-stream";
import { cn } from "@/lib/utils";

const TONE_DOT = { info: "text-sky-500", ok: "text-emerald-500", warn: "text-amber-500", error: "text-red-500" } as const;
const STATUS_TONE: Record<string, string> = {
  queued: "bg-zinc-100 text-zinc-700",
  running: "bg-sky-100 text-sky-700",
  waiting: "bg-amber-100 text-amber-800",
  succeeded: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-zinc-100 text-zinc-500",
};

function coerce(v: InputVariable, raw: string): unknown {
  if (raw === "") return undefined;
  if (v.type === "number") return Number(raw);
  if (v.type === "boolean") return raw === "true";
  if (v.type === "json") {
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  return raw;
}

/**
 * Test an agent or workflow without leaving the page: inputs, run, live
 * timeline, the decisions it waits on, and its answer. The live view is
 * handed up (``onView``) so the canvas can light up the running steps.
 */
export function Playground({
  kind,
  targetId,
  token,
  fields = [],
  beforeRun,
  onView,
  onClose,
  stepName = (id: string) => id,
}: {
  kind: "agent" | "workflow";
  targetId: string;
  token: string;
  fields?: InputVariable[];
  beforeRun?: () => Promise<boolean>;
  onView: (view: RunView) => void;
  onClose: () => void;
  stepName?: (nodeId: string) => string;
}) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const { view, live } = useRunStream(runId, token);

  useEffect(() => onView(view), [view, onView]);

  const history = useQuery({
    queryKey: ["builder-runs", kind, targetId],
    queryFn: () => builderApi.listRuns(token, kind === "agent" ? { agent_id: targetId } : { workflow_id: targetId }),
    enabled: !!token,
  });

  const start = useMutation({
    mutationFn: async (): Promise<Run | null> => {
      setProblems([]);
      if (beforeRun && !(await beforeRun())) return null;
      if (kind === "agent") return builderApi.startAgentRun(token, targetId, input);
      const variables: Record<string, unknown> = {};
      for (const f of fields) {
        const v = coerce(f, values[f.name] ?? "");
        if (v !== undefined) variables[f.name] = v;
      }
      return builderApi.startWorkflowRun(token, targetId, input, variables);
    },
    onSuccess: (run) => {
      if (!run) return;
      setRunId(run.id);
      void queryClient.invalidateQueries({ queryKey: ["builder-runs", kind, targetId] });
    },
    onError: (err) => {
      const list = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      setProblems(list.length ? list : [{ code: "error", message: err instanceof Error ? err.message : "Couldn't start the run." }]);
    },
  });

  const cancel = useMutation({ mutationFn: () => builderApi.cancelRun(token, runId!) });
  const active = runId !== null && !isFinished(view.status);
  const missingRequired = fields.some((f) => f.required && !(values[f.name] ?? "").trim());

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3">
        <Play className="h-4 w-4 text-indigo-600" />
        <h2 className="flex-1 text-sm font-semibold text-zinc-900">Playground</h2>
        {(history.data ?? []).length > 0 && (
          <Select className="h-8 w-44 text-xs" value={runId ?? ""} onChange={(e) => setRunId(e.target.value || null)} aria-label="Earlier runs">
            <option value="">Earlier runs…</option>
            {(history.data ?? []).slice(0, 15).map((r) => (
              <option key={r.id} value={r.id}>
                {new Date(r.created_at).toLocaleString()} · {r.status}
                {r.definition_version ? ` · v${r.definition_version}` : ""}
                {r.schedule_id ? " · scheduled" : ""}
              </option>
            ))}
          </Select>
        )}
        <button type="button" aria-label="Close playground" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!start.isPending) start.mutate();
          }}
        >
          <Field label={kind === "agent" ? "Ask the agent" : "Request"}>
            <Textarea rows={3} value={input} placeholder={kind === "agent" ? "What should it do?" : "What should this run work on?"} onChange={(e) => setInput(e.target.value)} />
          </Field>
          {fields.map((f) => (
            <Field key={f.name} label={`${f.label || f.name}${f.required ? " *" : ""}`} hint={f.description ?? undefined}>
              {f.type === "boolean" ? (
                <Select value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                  <option value="">—</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </Select>
              ) : (
                <Input className="h-9" type={f.type === "number" ? "number" : "text"} value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
              )}
            </Field>
          ))}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={start.isPending || (kind === "agent" && !input.trim()) || missingRequired}>
              {start.isPending ? <Spinner className="h-4 w-4" /> : <Play />} Run
            </Button>
            {active && (
              <Button type="button" size="sm" variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                <Square /> Stop
              </Button>
            )}
          </div>
        </form>

        {problems.length > 0 && (
          <div className="space-y-1 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-xs font-semibold text-red-800">It can&apos;t run yet</p>
            {problems.map((p, i) => (
              <p key={i} className="flex gap-1.5 text-xs text-red-700">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                <span>
                  {p.message}
                  {p.code === "not_connected" && (
                    <a href="/user/agents" className="ml-1 font-medium underline">Connect</a>
                  )}
                </span>
              </p>
            ))}
          </div>
        )}

        {runId && (
          <div className="flex items-center gap-2 text-xs">
            <span className={cn("rounded-full px-2 py-0.5 font-semibold", STATUS_TONE[view.status ?? "queued"])}>{view.status ?? "connecting"}</span>
            {live && !isFinished(view.status) && <span className="flex items-center gap-1 text-emerald-600"><Radio className="h-3 w-3" /> live</span>}
            {view.status === "waiting" && <span className="text-amber-700">Waiting for your decision below</span>}
          </div>
        )}

        {view.approvals.map((a) => (
          <ApprovalCard key={a.id} approval={a} token={token} onDone={() => undefined} />
        ))}

        {view.output !== null && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3">
            <p className="mb-1 text-xs font-semibold text-emerald-800">Answer</p>
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-800">{view.output}</div>
            {view.sources.length > 0 && <p className="mt-2 text-[11px] text-zinc-500">Sources: {view.sources.join(", ")}</p>}
          </div>
        )}
        {view.status === "failed" && view.error && <p className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{view.error}</p>}

        {view.guardrails.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-amber-900">
              <ShieldAlert className="h-3.5 w-3.5" /> Guardrails
            </p>
            <ul className="space-y-1">
              {view.guardrails.map((g, i) => (
                <li key={i} className={cn("text-xs", g.severity === "high" ? "text-red-700" : g.severity === "medium" ? "text-amber-800" : "text-zinc-600")}>
                  {kind === "workflow" && g.node_id && <span className="font-medium">{stepName(g.node_id)}: </span>}
                  {g.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {view.timeline.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">Timeline</p>
            <ol className="space-y-1">
              {view.timeline.map((t) => (
                <li key={t.key} className="flex gap-2 text-xs text-zinc-700">
                  <Circle className={cn("mt-0.5 h-2.5 w-2.5 shrink-0 fill-current", TONE_DOT[t.tone])} />
                  <span>
                    {t.nodeId && <span className="font-medium text-zinc-900">{stepName(t.nodeId)} </span>}
                    {t.text}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}
