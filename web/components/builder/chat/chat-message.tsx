"use client";

import { createContext, memo, useContext, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, ChevronRight, Copy, FileText, Image as ImageIcon, Info, Loader2, Pencil, RotateCw, ShieldAlert, Wand2, Wrench, XCircle } from "lucide-react";

import { MarkdownView } from "@/components/builder/chat/markdown-view";
import { AnswerView } from "@/components/builder/run-output";
import { TypeIcon } from "@/components/builder/type-icon";
import { Menu } from "@/components/ui/menu";
import { builderApi } from "@/lib/builder/api";
import type { OutputConfig } from "@/lib/builder/types";
import { answerJsonText } from "@/lib/builder/answer-json";
import { formatCost, formatDuration, formatTokens, hueOf, initials, runDurationMs, trailSummary } from "@/lib/builder/chat";
import { displayTool } from "@/lib/builder/run-state";
import type { Attachment, GuardrailFlag, Run, RunToolCall } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** Set by a chat: its avatars are the agent's or workflow's type icon, not a person's initials. */
export const AvatarKind = createContext<"agent" | "workflow" | null>(null);

export function Avatar({ name, size = 28, live = false }: { name: string; size?: number; live?: boolean }) {
  const kind = useContext(AvatarKind);
  if (kind) return <TypeIcon kind={kind} size={size >= 48 ? "lg" : size >= 32 ? "md" : "sm"} live={live} />;
  const h = hueOf(name);
  return (
    <span
      aria-hidden
      className={cn("relative flex shrink-0 items-center justify-center rounded-[32%] font-semibold tracking-tight", live && "animate-pulse")}
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

/** A small icon-only action under a message. */
const ICON_BUTTON = "inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-40 cursor-pointer";

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
      aria-label={copied ? "Copied" : "Copy"}
      title={copied ? "Copied" : "Copy"}
      className={ICON_BUTTON}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

/** A file sent with a message, as a small chip. */
export function FileChip({ file, onRemove }: { file: Pick<Attachment, "filename" | "kind">; onRemove?: () => void }) {
  const Icon = file.kind === "image" ? ImageIcon : FileText;
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-zinc-700">
      <Icon className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
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
        <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[var(--surface-strong)] px-4 py-2.5 text-sm leading-relaxed text-zinc-900">{text}</div>
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="mt-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100 cursor-pointer"
          >
            <Pencil className="h-3 w-3" /> Edit
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
  started: <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500" />,
};

function ToolCallRow({ call, stepName }: { call: RunToolCall; stepName?: string }) {
  const failed = call.is_error || call.status === "failed";
  const hasArgs = call.arguments && Object.keys(call.arguments).length > 0;
  return (
    <details className="group/call rounded-md border border-zinc-200">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-xs">
        {CALL_ICON[failed ? "failed" : call.status] ?? <Wrench className="h-3.5 w-3.5 text-zinc-400" />}
        <span className="min-w-0 truncate font-mono font-medium text-zinc-800">{displayTool(call.tool_name)}</span>
        {stepName && <span className="hidden shrink-0 text-xs text-zinc-500 sm:inline">in {stepName}</span>}
        {call.risk !== "read" && (
          <span className="shrink-0 rounded bg-amber-50 px-1.5 text-xs font-medium capitalize text-amber-700">{call.risk}</span>
        )}
        {call.status === "declined" && <span className="shrink-0 text-xs font-medium text-amber-700">declined</span>}
        <span className="ml-auto shrink-0 tabular-nums text-xs text-zinc-500">{call.duration_ms != null ? formatDuration(call.duration_ms) : ""}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform group-open/call:rotate-180" />
      </summary>
      <div className="space-y-2 border-t border-zinc-100 p-2.5">
        {hasArgs && (
          <div>
            <p className="mb-1 text-xs font-medium text-zinc-500">Sent</p>
            <pre className="max-h-40 overflow-auto rounded bg-zinc-50 p-2 font-mono text-xs leading-relaxed text-zinc-700">{JSON.stringify(call.arguments, null, 2)}</pre>
          </div>
        )}
        <div>
          <p className="mb-1 text-xs font-medium text-zinc-500">{failed ? "Error" : "Got back"}</p>
          <p className={cn("max-h-56 overflow-auto whitespace-pre-wrap break-words rounded p-2 text-xs leading-relaxed", failed ? "bg-red-50 text-red-700" : "bg-zinc-50 text-zinc-600")}>
            {call.result_preview || (call.status === "declined" ? "You declined this call." : "(nothing)")}
          </p>
        </div>
      </div>
    </details>
  );
}

/** "How it ran": the tools a finished run called, each expandable. */
/** "▸ Used 3 tools · 44 s" above an answer; open it to see each call. */
export function RunTrail({ run, stepName, ms }: { run: Run; stepName?: (nodeId: string) => string; ms?: number | null }) {
  const summary = trailSummary(run);
  if (!summary) return null;
  return (
    <details className="group/trail mb-2">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md py-0.5 text-xs text-zinc-500 hover:text-zinc-900 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open/trail:rotate-90" />
        {summary}
        {ms != null && <span className="tabular-nums"> · {formatDuration(ms)}</span>}
      </summary>
      <div className="mt-1.5 space-y-1.5 border-l-2 border-zinc-200 pl-3">
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

/** Ways to see a workflow's answer again, one click each: its output step re-run on what reached it
 *  (POST /workflows/{id}/output-preview) — nothing else runs, and each is fetched once. JSON is
 *  made here from the answer itself instead (``local``), so it's exactly the answer, the same every time. */
const RESHAPES: { key: string; label: string; config: OutputConfig; local?: boolean }[] = [
  { key: "report", label: "Report", config: { format: "formatted" } },
  {
    key: "brief", label: "Brief", config: {
      format: "formatted",
      custom_sections: [
        { title: "Bottom line", hint: "The answer in 2 sentences." },
        { title: "What we found", hint: "3-6 bullets with the most important facts." },
        { title: "Recommended actions", hint: "Numbered and concrete, only if the answer implies something to do." },
      ],
    },
  },
  { key: "tables", label: "Tables", config: { format: "markdown", instructions: "Put every list of records into markdown tables (one row each, every field kept, URLs and dates exact); keep short headings between them." } },
  { key: "text", label: "Plain text", config: { format: "text" } },
  { key: "json", label: "JSON", config: { format: "json" }, local: true },
  { key: "hindi", label: "हिंदी", config: { format: "markdown", language: "Hindi" } },
];

/** Which run's output step to reshape. */
export type Reshape = { token: string; workflowId: string; nodeId: string };

function useReshaped(run: Run, reshape: Reshape | undefined, key: string) {
  const choice = RESHAPES.find((r) => r.key === key);
  return useQuery({
    queryKey: ["builder-reshape", run.id, key],
    queryFn: () => builderApi.outputPreview(reshape!.token, reshape!.workflowId, { run_id: run.id, node_id: reshape!.nodeId, output_config: choice!.config }),
    enabled: !!reshape && !!choice && !choice.local,
    staleTime: Infinity,
  });
}

/** A finished turn: the answer (or why there isn't one), how it ran, and a quiet footer. */
export const AnswerMessage = memo(function AnswerMessage({
  run,
  name,
  latest,
  onRetry,
  retryDisabled,
  stepName,
  reshape,
}: {
  run: Run;
  name: string;
  latest: boolean;
  onRetry: () => void;
  retryDisabled: boolean;
  stepName?: (nodeId: string) => string;
  /** A workflow's answer: offer its other formats. */
  reshape?: Reshape;
}) {
  const original = run.output_text ?? run.output?.text ?? "";
  const [shape, setShape] = useState("original");
  const reshaped = useReshaped(run, shape === "original" ? undefined : reshape, shape);
  const local = RESHAPES.find((r) => r.key === shape)?.local;
  const text =
    shape === "original"
      ? original
      : local
        ? answerJsonText(original, { question: run.input?.text, sources: run.output?.sources })
        : reshaped.data?.text ?? "";
  const ms = runDurationMs(run);
  const canReshape = !!reshape && run.status === "succeeded" && !!original;
  const [details, setDetails] = useState(false);
  const tokens = (run.prompt_tokens ?? 0) + (run.completion_tokens ?? 0);
  const shapeLabel = shape === "original" ? "Original" : RESHAPES.find((r) => r.key === shape)?.label;
  return (
    <div className="group/answer flex gap-3">
      <Avatar name={name} />
      <div className="min-w-0 flex-1 pt-0.5">
        <RunTrail run={run} stepName={stepName} ms={ms} />
        <GuardrailNotes flags={run.output?.guardrails ?? []} />
        {run.status === "failed" ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <p className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> It couldn&apos;t finish</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-sm">{run.error || "Something went wrong."}</p>
          </div>
        ) : run.status === "cancelled" ? (
          <div className="space-y-2">
            <p className="text-sm italic text-zinc-500">Stopped before it finished.</p>
            {text && <MarkdownView text={text} />}
          </div>
        ) : shape !== "original" && !local && reshaped.isPending ? (
          <p className="flex items-center gap-1.5 text-sm text-zinc-500"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Reshaping the answer…</p>
        ) : shape !== "original" && !local && reshaped.error ? (
          <p className="text-sm text-red-600">{reshaped.error instanceof Error ? reshaped.error.message : "Couldn't reshape it."}</p>
        ) : text ? (
          <AnswerView text={text} />
        ) : (
          <p className="text-sm text-zinc-500">(no answer)</p>
        )}
        {(run.output?.sources?.length ?? 0) > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
            Sources
            {run.output!.sources!.map((src) => (
              <span key={src} className="rounded-md bg-zinc-100 px-2 py-0.5 text-zinc-700">{src}</span>
            ))}
          </div>
        )}
        {/* The latest answer keeps its actions in view; earlier ones show them on hover (always on touch). */}
        <div className={cn("mt-2 flex flex-wrap items-center gap-0.5 transition-opacity", !latest && "sm:opacity-0 sm:group-hover/answer:opacity-100 sm:focus-within:opacity-100")}>
          {text && <CopyButton text={text} />}
          <button type="button" onClick={onRetry} disabled={retryDisabled} aria-label="Retry" title="Ask the same thing again" className={ICON_BUTTON}>
            <RotateCw className="h-4 w-4" />
          </button>
          {canReshape && (
            <Menu
              label="See the answer as"
              trigger={<><Wand2 className="h-3.5 w-3.5" /> {shape === "original" ? "View as" : shapeLabel} <ChevronDown className="h-3 w-3" /></>}
              triggerClassName={cn("inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer", shape === "original" ? "text-zinc-500" : "bg-zinc-100 text-zinc-900")}
              items={[{ key: "original", label: "Original" }, ...RESHAPES].map((r) => ({ label: r.label, checked: shape === r.key, onClick: () => setShape(r.key) }))}
            />
          )}
          <button type="button" onClick={() => setDetails((d) => !d)} aria-expanded={details} aria-label="Details" title="Time, tokens and cost" className={cn(ICON_BUTTON, details && "bg-zinc-100 text-zinc-900")}>
            <Info className="h-4 w-4" />
          </button>
        </div>
        {details && (
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums text-zinc-500">
            <span>{new Date(run.created_at).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
            {ms != null && <span>Took {formatDuration(ms)}</span>}
            {tokens > 0 && (
              <span title={`${run.prompt_tokens ?? 0} tokens in, ${run.completion_tokens ?? 0} out${run.cost_usd == null ? " · this model has no known price" : ""}`}>
                {formatTokens(tokens)} tokens{run.cost_usd != null ? ` · ${formatCost(run.cost_usd)}` : ""}
              </span>
            )}
            {run.definition_version ? <span>Version {run.definition_version}</span> : null}
          </p>
        )}
      </div>
    </div>
  );
});
