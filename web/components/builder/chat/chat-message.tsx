"use client";

import { memo, useState, type ReactNode } from "react";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Copy, FileText, Image as ImageIcon, Loader2, Pencil, RotateCw, ShieldAlert, Wrench, XCircle } from "lucide-react";

import { MarkdownView } from "@/components/builder/chat/markdown-view";
import { formatCost, formatDuration, formatTokens, hueOf, initials, runDurationMs, trailSummary } from "@/lib/builder/chat";
import { displayTool } from "@/lib/builder/run-state";
import type { Attachment, GuardrailFlag, Run, RunToolCall } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

export function Avatar({ name, size = 28, live = false }: { name: string; size?: number; live?: boolean }) {
  const h = hueOf(name);
  return (
    <span
      aria-hidden
      className={cn("relative flex shrink-0 items-center justify-center rounded-[32%] font-bold tracking-tight", live && "animate-pulse")}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(9, size * 0.34),
        background: `hsl(${h} 40% 93%)`,
        color: `hsl(${h} 45% 28%)`,
        border: `1px solid hsl(${h} 32% 80%)`,
      }}
    >
      {initials(name)}
    </span>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1 hover:text-zinc-800 cursor-pointer"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** A file sent with a message, as a small chip. */
export function FileChip({ file, onRemove }: { file: Pick<Attachment, "filename" | "kind">; onRemove?: () => void }) {
  const Icon = file.kind === "image" ? ImageIcon : FileText;
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2 py-1 text-[11px] text-zinc-700">
      <Icon className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
      <span className="min-w-0 truncate">{file.filename}</span>
      {onRemove && (
        <button type="button" aria-label={`Remove ${file.filename}`} onClick={onRemove} className="shrink-0 text-zinc-400 hover:text-red-600 cursor-pointer">
          <XCircle className="h-3.5 w-3.5" />
        </button>
      )}
    </span>
  );
}

export function UserMessage({ text, onEdit, files = [] }: { text: string; onEdit?: () => void; files?: Pick<Attachment, "id" | "filename" | "kind">[] }) {
  return (
    <div className="group flex justify-end">
      <div className="flex max-w-[85%] flex-col items-end">
        {files.length > 0 && (
          <div className="mb-1.5 flex flex-wrap justify-end gap-1.5">
            {files.map((f) => <FileChip key={f.id} file={f} />)}
          </div>
        )}
        <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">{text}</div>
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="mt-1 inline-flex items-center gap-1 text-[11px] text-zinc-400 opacity-100 transition hover:text-zinc-700 sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100 cursor-pointer"
          >
            <Pencil className="h-3 w-3" /> Edit &amp; resend
          </button>
        )}
      </div>
    </div>
  );
}

const CALL_ICON: Record<string, ReactNode> = {
  succeeded: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  declined: <XCircle className="h-3.5 w-3.5 text-amber-500" />,
  started: <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-500" />,
};

function ToolCallRow({ call, stepName }: { call: RunToolCall; stepName?: string }) {
  const failed = call.is_error || call.status === "failed";
  const hasArgs = call.arguments && Object.keys(call.arguments).length > 0;
  return (
    <details className="group/call rounded-lg border border-zinc-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-xs">
        {CALL_ICON[failed ? "failed" : call.status] ?? <Wrench className="h-3.5 w-3.5 text-zinc-400" />}
        <span className="min-w-0 truncate font-mono font-medium text-zinc-800">{displayTool(call.tool_name)}</span>
        {stepName && <span className="hidden shrink-0 text-[10px] text-zinc-400 sm:inline">in {stepName}</span>}
        {call.risk !== "read" && (
          <span className="shrink-0 rounded bg-amber-50 px-1 text-[10px] font-semibold uppercase text-amber-700">{call.risk}</span>
        )}
        {call.status === "declined" && <span className="shrink-0 text-[10px] font-medium text-amber-700">declined</span>}
        <span className="ml-auto shrink-0 tabular-nums text-[10px] text-zinc-400">{call.duration_ms != null ? formatDuration(call.duration_ms) : ""}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform group-open/call:rotate-180" />
      </summary>
      <div className="space-y-2 border-t border-zinc-100 p-2.5">
        {hasArgs && (
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">Sent</p>
            <pre className="max-h-40 overflow-auto rounded bg-zinc-50 p-2 font-mono text-[10.5px] leading-relaxed text-zinc-700">{JSON.stringify(call.arguments, null, 2)}</pre>
          </div>
        )}
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">{failed ? "Error" : "Got back"}</p>
          <p className={cn("max-h-56 overflow-auto whitespace-pre-wrap break-words rounded p-2 text-[11px] leading-relaxed", failed ? "bg-red-50 text-red-700" : "bg-zinc-50 text-zinc-600")}>
            {call.result_preview || (call.status === "declined" ? "You declined this call." : "(nothing)")}
          </p>
        </div>
      </div>
    </details>
  );
}

/** "How it ran": the tools a finished run called, each expandable. */
export function RunTrail({ run, stepName }: { run: Run; stepName?: (nodeId: string) => string }) {
  const summary = trailSummary(run);
  if (!summary) return null;
  return (
    <details className="group/trail mt-2 rounded-xl border border-zinc-200 bg-zinc-50/60">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-zinc-600 hover:text-zinc-900">
        <Wrench className="h-3.5 w-3.5" /> How it ran <span className="font-normal text-zinc-400">· {summary}</span>
        <ChevronDown className="ml-auto h-3.5 w-3.5 transition-transform group-open/trail:rotate-180" />
      </summary>
      <div className="space-y-1.5 border-t border-zinc-200 p-2">
        {(run.tool_calls ?? []).map((c) => (
          <ToolCallRow key={c.id} call={c} stepName={run.kind === "workflow" && c.node_id ? stepName?.(c.node_id) : undefined} />
        ))}
      </div>
    </details>
  );
}

export function GuardrailNotes({ flags }: { flags: GuardrailFlag[] }) {
  const shown = flags.filter((f) => f.severity !== "low");
  if (!shown.length) return null;
  return (
    <div className="mb-2 space-y-1.5">
      {shown.map((f, i) => (
        <p
          key={i}
          className={cn(
            "flex items-start gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs",
            f.severity === "high" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-800",
          )}
        >
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {f.message}
        </p>
      ))}
    </div>
  );
}

/** A finished turn: the answer (or why there isn't one), how it ran, and a quiet footer. */
export const AnswerMessage = memo(function AnswerMessage({
  run,
  name,
  latest,
  onRetry,
  retryDisabled,
  stepName,
}: {
  run: Run;
  name: string;
  latest: boolean;
  onRetry: () => void;
  retryDisabled: boolean;
  stepName?: (nodeId: string) => string;
}) {
  const text = run.output_text ?? run.output?.text ?? "";
  const ms = runDurationMs(run);
  return (
    <div className="group/answer flex gap-3">
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <GuardrailNotes flags={run.output?.guardrails ?? []} />
        {run.status === "failed" ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <p className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> It couldn&apos;t finish</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs">{run.error || "Something went wrong."}</p>
          </div>
        ) : run.status === "cancelled" ? (
          <div className="space-y-2">
            <p className="text-sm italic text-zinc-400">Stopped before it finished.</p>
            {text && <MarkdownView text={text} />}
          </div>
        ) : text ? (
          <MarkdownView text={text} />
        ) : (
          <p className="text-sm text-zinc-400">(no answer)</p>
        )}
        {(run.output?.sources?.length ?? 0) > 0 && (
          <p className="mt-2 text-[11px] text-zinc-500">Sources: {run.output!.sources!.join(", ")}</p>
        )}
        <RunTrail run={run} stepName={stepName} />
        <div className={cn("mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-zinc-400 transition-opacity", !latest && "sm:opacity-0 sm:group-hover/answer:opacity-100")}>
          {ms != null && <span className="tabular-nums">{formatDuration(ms)}</span>}
          {(run.prompt_tokens ?? 0) + (run.completion_tokens ?? 0) > 0 && (
            <span className="tabular-nums" title={`${run.prompt_tokens ?? 0} tokens in, ${run.completion_tokens ?? 0} out${run.cost_usd == null ? " · this model has no known price" : ""}`}>
              {formatTokens((run.prompt_tokens ?? 0) + (run.completion_tokens ?? 0))} tokens{run.cost_usd != null ? ` · ${formatCost(run.cost_usd)}` : ""}
            </span>
          )}
          <span>{new Date(run.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
          {run.definition_version ? <span>v{run.definition_version}</span> : null}
          {text && <CopyButton text={text} />}
          <button type="button" onClick={onRetry} disabled={retryDisabled} className="inline-flex items-center gap-1 hover:text-zinc-800 disabled:opacity-40 cursor-pointer" title="Ask the same thing again">
            <RotateCw className="h-3 w-3" /> Retry
          </button>
        </div>
      </div>
    </div>
  );
});
