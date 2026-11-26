"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, FileText, FlaskConical, Pin, PinOff, Play, X } from "lucide-react";

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
  succeeded: "border border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
  failed: "border border-red-500/30 bg-red-500/15 text-red-300",
  cancelled: "border border-white/10 bg-white/5 text-zinc-400",
  waiting: "border border-amber-500/30 bg-amber-500/15 text-amber-300",
};

export type UpstreamSource = {
  nodeId: string;
  title: string;
  output: string;
  pinned: boolean;
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
  upstreamSources = [],
  pinnedOutput,
  onPinOutput,
  onClose,
}: {
  workflowId: string;
  node: WorkflowNode;
  title: string;
  token: string;
  initialInput: string;
  upstreamSources?: UpstreamSource[];
  pinnedOutput?: string | null;
  onPinOutput?: (text: string | null) => void;
  onClose: () => void;
}) {
  const defaultFromUpstream =
    upstreamSources.length > 0
      ? upstreamSources.map((s) => (upstreamSources.length > 1 ? `## ${s.title}\n${s.output}` : s.output)).join("\n\n")
      : initialInput;
  const [input, setInput] = useState(defaultFromUpstream);
  const [runId, setRunId] = useState<string | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const { view } = useRunStream(runId, token);
  const running = !!runId && !isFinished(view.status);
  const outputPinned = view.output !== null && pinnedOutput === view.output;

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
      <div className="flex items-center gap-2.5 border-b border-white/10 px-3.5 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/15 text-emerald-300">
          <FlaskConical className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-zinc-100">Test · {title}</h2>
          <p className="truncate text-xs text-zinc-400">Only this step, reusing saved/pinned upstream output.</p>
        </div>
        <button type="button" aria-label="Close" title="Close" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-white/5 hover:text-zinc-100 cursor-pointer">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3.5 py-3">
        {upstreamSources.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium text-zinc-400">Reuse output from previous step:</p>
            <div className="flex flex-wrap gap-1.5">
              {upstreamSources.map((src) => (
                <button
                  key={src.nodeId}
                  type="button"
                  onClick={() => setInput(src.output)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                    input === src.output
                      ? "border-indigo-400/50 bg-indigo-500/20 text-indigo-200"
                      : "border-white/10 bg-white/[0.04] text-zinc-300 hover:border-white/20 hover:bg-white/[0.08]",
                  )}
                  title={src.output.slice(0, 220)}
                >
                  {src.pinned && <Pin className="h-2.5 w-2.5 text-amber-300" />}
                  <span className="max-w-[140px] truncate">{src.title}</span>
                </button>
              ))}
              {initialInput.trim() && (
                <button
                  type="button"
                  onClick={() => setInput(initialInput)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors cursor-pointer",
                    input === initialInput
                      ? "border-indigo-400/50 bg-indigo-500/20 text-indigo-200"
                      : "border-white/10 bg-white/[0.04] text-zinc-400 hover:text-zinc-200",
                  )}
                >
                  Workflow prompt
                </button>
              )}
            </div>
          </div>
        )}

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
          <div className="space-y-1 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5">
            {problems.map((p, i) => (
              <p key={i} className="flex gap-1.5 text-xs text-red-300"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{p.message}</p>
            ))}
          </div>
        )}

        {runId && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <span className={cn("inline-block rounded-full px-2 py-0.5 text-xs font-semibold", STATUS_TONE[view.status ?? ""] ?? "border border-sky-500/30 bg-sky-500/15 text-sky-300")}>
                {view.status ?? "starting"}
              </span>
              {view.output !== null && onPinOutput && (
                <button
                  type="button"
                  onClick={() => onPinOutput(outputPinned ? null : view.output!)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                    outputPinned
                      ? "border-amber-400/40 bg-amber-500/15 text-amber-200 hover:border-red-400/40 hover:text-red-200"
                      : "border-indigo-400/40 bg-indigo-500/15 text-indigo-200 hover:bg-indigo-500/25",
                  )}
                >
                  {outputPinned ? <><PinOff className="h-3 w-3" /> Unpin output</> : <><Pin className="h-3 w-3" /> Pin output for next steps</>}
                </button>
              )}
            </div>
            {view.approvals.map((a) => <ApprovalCard key={a.id} approval={a} token={token} onDone={() => undefined} />)}
            {view.output !== null && (
              <div className="rounded-lg border border-white/10 bg-zinc-950/60 p-2.5 text-sm text-zinc-100"><MarkdownView text={view.output} /></div>
            )}
            {view.status === "failed" && view.error && <p className="text-xs text-red-300">{view.error}</p>}
            {view.guardrails.map((g, i) => <p key={i} className="text-xs text-amber-300">Guardrail: {g.message}</p>)}
            {/* Only this step's own lines (the input and output around it are scaffolding). */}
            <RunTimeline view={{ ...view, timeline: view.timeline.filter((t) => !t.nodeId || t.nodeId === "step") }} stepName={() => title} />
          </div>
        )}
      </div>
    </div>
  );
}

/** A step's whole answer from the last run on the canvas (with optional Pin action). */
export function StepResult({
  title,
  text,
  isPinned,
  onPin,
  onClose,
}: {
  title: string;
  text: string;
  isPinned?: boolean;
  onPin?: (pinned: boolean) => void;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex max-h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-white/10 px-3.5 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/15 text-sky-300"><FileText className="h-3.5 w-3.5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-zinc-100">{title}</h2>
          <p className="truncate text-xs text-zinc-400">{isPinned ? "Pinned sample output" : "Its output in the last run"}</p>
        </div>
        {onPin && (
          <button
            type="button"
            title={isPinned ? "Unpin output" : "Pin this output for downstream step tests"}
            onClick={() => onPin(!isPinned)}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer",
              isPinned
                ? "border-amber-400/40 bg-amber-500/15 text-amber-200 hover:border-red-400/40 hover:text-red-200"
                : "border-white/10 text-zinc-300 hover:bg-white/5 hover:text-white",
            )}
          >
            {isPinned ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}
            <span>{isPinned ? "Unpin" : "Pin"}</span>
          </button>
        )}
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
          className="rounded-md p-1.5 text-zinc-400 hover:bg-white/5 hover:text-zinc-100 cursor-pointer"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
        <button type="button" aria-label="Close" title="Close" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-white/5 hover:text-zinc-100 cursor-pointer">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3.5 py-3 text-sm text-zinc-100">
        <MarkdownView text={text} />
      </div>
    </div>
  );
}
