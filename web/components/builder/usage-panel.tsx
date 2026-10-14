"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Coins, X } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { DailyBars } from "@/components/charts/daily-bars";
import { builderApi } from "@/lib/builder/api";
import { formatCost, formatTokens } from "@/lib/builder/chat";
import { cn } from "@/lib/utils";

const WINDOWS = [7, 30, 90] as const;

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 p-3">
      <p className="text-[11px] font-medium text-zinc-500">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-zinc-900">{value}</p>
      {note && <p className="mt-0.5 text-[11px] text-zinc-400">{note}</p>}
    </div>
  );
}

/** Runs, tokens and estimated cost of an agent or workflow over a window. */
export function UsagePanel({ kind, targetId, token, onClose }: { kind: "agent" | "workflow"; targetId: string; token: string; onClose: () => void }) {
  const [days, setDays] = useState<(typeof WINDOWS)[number]>(30);
  const usage = useQuery({ queryKey: ["builder-usage", kind, targetId, days], queryFn: () => builderApi.usage(token, kind, targetId, days), enabled: !!token });
  const u = usage.data;

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3">
        <Coins className="h-4 w-4 text-amber-500" />
        <h2 className="flex-1 text-sm font-semibold text-zinc-900">Usage and cost</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-zinc-500">{u?.scope === "everyone" ? "Everyone's runs (numbers only)" : "Your runs"}</p>
          <div className="flex rounded-lg border border-zinc-200 p-0.5" role="group" aria-label="Window">
            {WINDOWS.map((d) => (
              <button
                key={d}
                type="button"
                aria-pressed={days === d}
                onClick={() => setDays(d)}
                className={cn("rounded-md px-2 py-1 text-[11px] font-medium cursor-pointer", days === d ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {usage.isLoading && <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>}
        {usage.isError && <p className="rounded-lg bg-red-50 p-3 text-xs text-red-700">Couldn&apos;t load usage.</p>}
        {u && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <Tile label="Estimated cost" value={formatCost(u.cost_usd) ?? "$0"} note={u.avg_cost_usd != null ? `${formatCost(u.avg_cost_usd)} a run on average` : undefined} />
              <Tile label="Runs" value={String(u.runs)} note={`${u.succeeded} succeeded · ${u.failed} failed`} />
              <Tile label="Tokens" value={formatTokens(u.prompt_tokens + u.completion_tokens)} note={`${formatTokens(u.prompt_tokens)} in · ${formatTokens(u.completion_tokens)} out`} />
              <Tile label="Average time" value={u.avg_seconds != null ? `${u.avg_seconds.toFixed(1)}s` : "—"} note="per finished run" />
            </div>
            {u.unpriced_runs > 0 && (
              <p className="rounded-lg bg-amber-50 p-2.5 text-[11px] text-amber-800">
                {u.unpriced_runs} run{u.unpriced_runs === 1 ? "" : "s"} used a model without a known price, so {u.unpriced_runs === 1 ? "its" : "their"} cost isn&apos;t in the total.
              </p>
            )}
            <DailyBars
              title="Runs per day"
              subtitle={`Last ${days} days (UTC)`}
              days={u.daily.map((d) => ({ date: d.date, good: d.succeeded, bad: d.failed }))}
              goodLabel="Succeeded"
              badLabel="Failed"
              empty="No runs in this window."
              summary={`${u.runs} runs · ${formatCost(u.cost_usd) ?? "$0"}`}
            />
            {Object.keys(u.by_purpose).length > 1 && (
              <p className="text-[11px] text-zinc-500">
                Includes {Object.entries(u.by_purpose).map(([p, n]) => `${n} ${p === "run" ? "regular" : p === "public" ? "published" : p}`).join(", ")} runs.
              </p>
            )}
            <p className="text-[11px] leading-relaxed text-zinc-400">
              Cost is an estimate from token counts and list prices of the model that answered; your provider&apos;s bill is the final word.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
