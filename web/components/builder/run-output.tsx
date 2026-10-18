"use client";

import { useState } from "react";
import { AlertTriangle, Check, Clock, Copy, Download, FileText, Maximize2, Wrench, X } from "lucide-react";

import { MarkdownView } from "@/components/builder/chat/markdown-view";
import type { RunNode, RunToolCall } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** A JSON answer (the output step's "json" format) as pretty JSON; anything else as rendered markdown. */
export function AnswerView({ text }: { text: string }) {
  const json = asJson(text);
  if (json !== null) {
    return <pre className="overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-relaxed text-zinc-800">{json}</pre>;
  }
  return <MarkdownView text={text} />;
}

function asJson(text: string): string | null {
  const t = text.trim();
  if (!(t.startsWith("{") || t.startsWith("["))) return null;
  try {
    return JSON.stringify(JSON.parse(t), null, 2);
  } catch {
    return null;
  }
}

/** Copy and download (as .json when it is JSON, else .md). */
export function AnswerActions({ text, name, onExpand }: { text: string; name: string; onExpand?: () => void }) {
  const [copied, setCopied] = useState(false);
  const isJson = asJson(text) !== null;
  const button = "rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer";
  return (
    <div className="flex items-center gap-0.5">
      <button
        type="button"
        aria-label="Copy"
        title="Copy"
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        className={button}
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <button
        type="button"
        aria-label="Download"
        title={`Download as .${isJson ? "json" : "md"}`}
        onClick={() => {
          const blob = new Blob([text], { type: isJson ? "application/json" : "text/markdown" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = `${name.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").toLowerCase() || "answer"}.${isJson ? "json" : "md"}`;
          a.click();
          URL.revokeObjectURL(a.href);
        }}
        className={button}
      >
        <Download className="h-3.5 w-3.5" />
      </button>
      {onExpand && (
        <button type="button" aria-label="Open in full" title="Open in full" onClick={onExpand} className={button}>
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function seconds(node: RunNode): string | null {
  if (!node.started_at || !node.finished_at) return null;
  const s = (new Date(node.finished_at).getTime() - new Date(node.started_at).getTime()) / 1000;
  return Number.isFinite(s) && s >= 0 ? (s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`) : null;
}

const STATUS_TONE: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  waiting: "bg-amber-100 text-amber-800",
  running: "bg-sky-100 text-sky-700",
};

type Tab = "output" | "input" | "tools";

/**
 * One step of a run, docked beside the canvas: what it answered, what reached it, and the tool
 * calls it made — with its status, time and tokens. Opened from a step's Result / its answer preview.
 */
export function StepRunPanel({
  title,
  kind,
  node,
  calls,
  onClose,
}: {
  title: string;
  kind: string;
  node: RunNode;
  calls: RunToolCall[];
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("output");
  const time = seconds(node);
  const tokens = (node.prompt_tokens ?? 0) + (node.completion_tokens ?? 0);
  const text = node.output_text ?? "";
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "output", label: "Output", show: true },
    { id: "input", label: "Input", show: !!node.input_text },
    { id: "tools", label: `Tools (${calls.length})`, show: calls.length > 0 },
  ];
  return (
    <div className="flex max-h-full min-h-0 flex-col">
      <div className="flex items-center gap-2.5 border-b border-zinc-200 px-3.5 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600"><FileText className="h-3.5 w-3.5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-zinc-900">{title}</h2>
          <p className="flex flex-wrap items-center gap-x-2 text-[11px] text-zinc-500">
            <span>{kind} · last run</span>
            <span className={cn("rounded-full px-1.5 py-px text-[10px] font-semibold", STATUS_TONE[node.status] ?? "bg-zinc-100 text-zinc-600")}>{node.status}</span>
            {time && <span className="inline-flex items-center gap-0.5"><Clock className="h-3 w-3" /> {time}</span>}
            {tokens > 0 && <span>{tokens.toLocaleString()} tokens</span>}
          </p>
        </div>
        {text && <AnswerActions text={text} name={title} />}
        <button type="button" aria-label="Close" title="Close" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex gap-1 border-b border-zinc-100 px-3.5 pt-2" role="tablist">
        {tabs.filter((t) => t.show).map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px border-b-2 px-2 pb-1.5 text-xs font-medium cursor-pointer",
              tab === t.id ? "border-indigo-500 text-indigo-700" : "border-transparent text-zinc-500 hover:text-zinc-800",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3.5 py-3 text-sm text-zinc-900">
        {node.error && (
          <p className="mb-3 flex items-start gap-1.5 rounded-md bg-red-50 px-2.5 py-2 text-xs text-red-700">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {node.error}
          </p>
        )}
        {tab === "output" && (text ? <AnswerView text={text} /> : <p className="text-xs text-zinc-400">{node.status === "running" ? "Still running…" : "No answer from this step."}</p>)}
        {tab === "input" && node.input_text && <AnswerView text={node.input_text} />}
        {tab === "tools" && (
          <ul className="space-y-2">
            {calls.map((c) => (
              <li key={c.id} className="rounded-lg border border-zinc-200 p-2">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-zinc-800">
                  <Wrench className="h-3.5 w-3.5 text-cyan-600" /> {c.tool_name}
                  <span className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", c.is_error ? "bg-red-100 text-red-700" : "bg-zinc-100 text-zinc-600")}>{c.is_error ? "error" : c.status}</span>
                  {c.duration_ms != null && <span className="ml-auto font-normal text-zinc-400">{(c.duration_ms / 1000).toFixed(1)}s</span>}
                </p>
                {Object.keys(c.arguments ?? {}).length > 0 && (
                  <pre className="mt-1.5 overflow-x-auto rounded bg-zinc-50 p-1.5 font-mono text-[10.5px] text-zinc-600">{JSON.stringify(c.arguments, null, 2)}</pre>
                )}
                {c.result_preview && <p className="mt-1.5 line-clamp-6 whitespace-pre-wrap text-[11px] text-zinc-600">{c.result_preview}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
