"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Eye, History, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import { toolName } from "@/lib/builder/graph";
import type { Version, VersionDetail } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** "5 min ago", "yesterday", "3 Oct". */
export function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (seconds < 60) return "just now";
  if (seconds < 3600) return rtf.format(-Math.round(seconds / 60), "minute");
  if (seconds < 86400) return rtf.format(-Math.round(seconds / 3600), "hour");
  if (seconds < 7 * 86400) return rtf.format(-Math.round(seconds / 86400), "day");
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Saved versions of an agent or workflow, newest first. A workflow version can
 * be previewed on the canvas (``onPreview``); an agent version opens in place.
 * Restoring is the parent's job (it owns the editor state and the version
 * number to check against).
 */
export function VersionHistory({
  kind,
  targetId,
  token,
  canRestore,
  dirty,
  previewing,
  restoring,
  onPreview,
  onRestore,
  onClose,
}: {
  kind: "agent" | "workflow";
  targetId: string;
  token: string;
  canRestore: boolean;
  dirty: boolean;
  previewing?: number | null;
  restoring: boolean;
  onPreview?: (version: number | null) => void;
  onRestore: (version: number) => void;
  onClose: () => void;
}) {
  const list = useQuery({
    queryKey: ["builder-versions", kind, targetId],
    queryFn: () => builderApi.listVersions(token, kind, targetId),
    enabled: !!token,
  });
  const [open, setOpen] = useState<number | null>(null);

  const restore = (v: Version) => {
    const warn = dirty ? "\n\nYour unsaved changes will be lost." : "";
    if (window.confirm(`Bring back version ${v.version}? It's saved as a new version, so nothing is lost from history.${warn}`)) onRestore(v.version);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-zinc-200 px-4 py-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900"><History className="h-4 w-4" /> Version history</h2>
          <p className="text-xs text-zinc-500">Every save is kept. Restoring makes a new version.</p>
        </div>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {list.isLoading && <div className="flex justify-center py-6"><Spinner className="h-5 w-5 text-zinc-400" /></div>}
        {list.data?.length === 0 && <p className="px-4 py-6 text-center text-xs text-zinc-400">No saved versions yet — they start with the next save.</p>}
        <ol>
          {(list.data ?? []).map((v) => (
            <li key={v.id} className={cn("border-b border-zinc-100 px-4 py-3", previewing === v.version && "bg-indigo-50/60")}>
              <div className="flex items-start gap-2">
                <span className={cn("mt-0.5 rounded px-1.5 py-0.5 text-[10px] font-bold", v.is_current ? "bg-emerald-100 text-emerald-800" : "bg-zinc-100 text-zinc-600")}>
                  v{v.version}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-zinc-900">
                    {v.note}
                    {v.is_current && <span className="ml-1.5 text-xs font-normal text-emerald-700">· current</span>}
                  </p>
                  <p className="text-xs text-zinc-500" title={new Date(v.created_at).toLocaleString()}>
                    {timeAgo(v.created_at)}{v.author_name ? ` · ${v.author_name}` : ""}
                  </p>
                  {v.summary && <p className="mt-1 text-xs text-zinc-700">{v.summary}</p>}
                </div>
              </div>
              {!v.is_current && (
                <div className="mt-2 flex flex-wrap gap-1.5 pl-8">
                  {kind === "workflow" && onPreview ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      onClick={() => onPreview(previewing === v.version ? null : v.version)}
                    >
                      <Eye /> {previewing === v.version ? "Stop preview" : "Preview"}
                    </Button>
                  ) : (
                    <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={() => setOpen(open === v.version ? null : v.version)}>
                      {open === v.version ? <ChevronDown /> : <ChevronRight />} What it was
                    </Button>
                  )}
                  {canRestore && (
                    <Button type="button" size="sm" variant="outline" className="h-7 text-xs" disabled={restoring} onClick={() => restore(v)}>
                      {restoring ? <Spinner className="h-3 w-3" /> : <RotateCcw />} Restore
                    </Button>
                  )}
                </div>
              )}
              {kind === "agent" && open === v.version && <AgentVersionDetail agentId={targetId} version={v.version} token={token} />}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function AgentVersionDetail({ agentId, version, token }: { agentId: string; version: number; token: string }) {
  const q = useQuery({
    queryKey: ["builder-version", "agent", agentId, version],
    queryFn: () => builderApi.getVersion(token, "agent", agentId, version),
    enabled: !!token,
    staleTime: Infinity, // a saved version never changes
  });
  if (!q.data) return <div className="mt-2 pl-8"><Spinner className="h-4 w-4 text-zinc-400" /></div>;
  const s: VersionDetail["snapshot"] = q.data.snapshot;
  const tools = ((s.config?.tool_ids as string[] | undefined) ?? []).map(toolName);
  const rows: [string, string][] = [
    ["Name", s.name ?? ""],
    ["Role", s.role ?? ""],
    ["Goal", s.goal ?? ""],
    ["Instructions", s.instructions || "—"],
    ["Model", [s.llm_provider, s.llm_model].filter(Boolean).join(" / ") || "Default"],
    ["Tools", tools.join(", ") || "None"],
  ];
  return (
    <dl className="mt-2 space-y-1.5 rounded-lg bg-zinc-50 p-2.5 pl-8 text-xs">
      {rows.map(([k, val]) => (
        <div key={k}>
          <dt className="font-medium text-zinc-500">{k}</dt>
          <dd className="line-clamp-4 whitespace-pre-wrap text-zinc-800">{val}</dd>
        </div>
      ))}
    </dl>
  );
}
