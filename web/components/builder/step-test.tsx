"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, FileText, FlaskConical, Play, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ApprovalCard } from "@/components/builder/approval-card";
import { MarkdownView } from "@/components/builder/chat/markdown-view";
import { Textarea } from "@/components/builder/fields";
import { RunTimeline } from "@/components/builder/playground";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { forSave } from "@/lib/builder/graph";
import { isFinished } from "@/lib/builder/run-state";
import type { Problem, WorkflowNode } from "@/lib/builder/types";
import { useRunStream } from "@/lib/builder/use-run-stream";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-zinc-100 text-zinc-600",
  waiting: "bg-amber-100 text-amber-800",
};

/** Whether a step has what it needs to be tried on its own. */
export function canTestStep(node: WorkflowNode): boolean {
  if (node.type === "agent") return !!(node.agent_id || node.draft_agent);
  if (node.type === "tool") return !!node.tool_id;
  return false;
}

/**
 * The canvas's Test: one step run by itself (input → this step → output), as it
 * is right now — unsaved edits included — with its answer, approvals and
 * timeline live. Tools really run; the run stays out of run history.
 */
export function StepTest({
  workflowId,
  node,
  title,
  token,
  initialInput,
  onClose,
}: {
  workflowId: string;
  node: WorkflowNode;
  title: string;
  token: string;
  initialInput: string;
  onClose: () => void;
}) {
  const [input, setInput] = useState(initialInput);
  const [runId, setRunId] = useState<string | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const { view } = useRunStream(runId, token);
  const running = !!runId && !isFinished(view.status);

  const start = useMutation({
    mutationFn: () => builderApi.testStep(token, workflowId, forSave([node])[0], input),
    onMutate: () => setProblems([]),
    onSuccess: (run) => setRunId(run.id),
    onError: (err) => {
      const list = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      setProblems(list.length ? list : [{ code: "error", message: err instanceof Error ? err.message : "Couldn't start the test." } as Problem]);
    },
  });
  const run = () => !running && !start.isPending && start.mutate();

  return (
    <div className="flex max-h-full min-h-0 flex-col">
      <div className="flex items-center gap-2.5 border-b border-zinc-200 px-3.5 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600"><FlaskConical className="h-3.5 w-3.5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-zinc-900">Test · {title}</h2>
          <p className="truncate text-[11px] text-zinc-500">Only this step, as it is now. Tools really run.</p>
        </div>
        <button type="button" aria-label="Close" title="Close" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3.5 py-3">
        <Textarea
          rows={3}
          aria-label="What to give this step"
          placeholder={node.type === "tool" ? "Text it gets from the step before (optional)" : "Ask it something…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              run();
            }
          }}
        />
        <Button size="sm" className="w-full" disabled={running || start.isPending || (node.type === "agent" && !input.trim())} onClick={run}>
          {running || start.isPending ? <Spinner className="h-4 w-4" /> : <Play />} {running ? "Running…" : runId ? "Run again" : "Run"}
        </Button>

        {problems.length > 0 && (
          <div className="space-y-1 rounded-lg bg-red-50 p-2.5">
            {problems.map((p, i) => (
              <p key={i} className="flex gap-1.5 text-xs text-red-700"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{p.message}</p>
            ))}
          </div>
        )}

        {runId && (
          <div className="space-y-3">
            <span className={cn("inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", STATUS_TONE[view.status ?? ""] ?? "bg-sky-100 text-sky-700")}>
              {view.status ?? "starting"}
            </span>
            {view.approvals.map((a) => <ApprovalCard key={a.id} approval={a} token={token} onDone={() => undefined} />)}
            {view.output !== null && (
              <div className="rounded-lg border border-zinc-200 p-2.5 text-sm text-zinc-900"><MarkdownView text={view.output} /></div>
            )}
            {view.status === "failed" && view.error && <p className="text-xs text-red-600">{view.error}</p>}
            {view.guardrails.map((g, i) => <p key={i} className="text-[11px] text-amber-700">Guardrail: {g.message}</p>)}
            {/* Only this step's own lines (the input and output around it are scaffolding). */}
            <RunTimeline view={{ ...view, timeline: view.timeline.filter((t) => !t.nodeId || t.nodeId === "step") }} stepName={() => title} />
          </div>
        )}
      </div>
    </div>
  );
}

/** A step's whole answer from the last run on the canvas. */
export function StepResult({ title, text, onClose }: { title: string; text: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex max-h-full min-h-0 flex-col">
      <div className="flex items-center gap-2.5 border-b border-zinc-200 px-3.5 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600"><FileText className="h-3.5 w-3.5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-zinc-900">{title}</h2>
          <p className="truncate text-[11px] text-zinc-500">Its answer in the last run</p>
        </div>
        <button
          type="button"
          aria-label="Copy the answer"
          title="Copy"
          onClick={() => {
            void navigator.clipboard?.writeText(text).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
          className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
        <button type="button" aria-label="Close" title="Close" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3.5 py-3 text-sm text-zinc-900">
        <MarkdownView text={text} />
      </div>
    </div>
  );
}
