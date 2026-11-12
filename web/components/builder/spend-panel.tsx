"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Network, OctagonX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import type { Spend } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** $0.0042 -> "$0.004", $1.5 -> "$1.50": money on the dashboard, never a long tail of digits. */
export function money(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
const monthName = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: "long", timeZone: "UTC" });

export const spendKey = ["builder-spend"];

export function useSpend(token: string) {
  return useQuery({ queryKey: spendKey, queryFn: () => builderApi.spend(token), enabled: !!token, refetchInterval: 60000 });
}

/** A line for "Needs your attention" once the month's limit is close or used up. */
export function SpendAlert({ spend }: { spend: Spend }) {
  if (spend.status === "ok" || spend.limit_usd == null) return null;
  const over = spend.status === "over";
  return (
    <a href="#spend" className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50">
      {over ? <OctagonX className="h-4 w-4 shrink-0 text-red-600" /> : <AlertTriangle className="h-4 w-4 shrink-0 text-amber-700" />}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-zinc-900">
          {over ? "Monthly limit used up: new runs are paused" : "Close to your monthly limit"}
        </span>
        <span className="block truncate text-xs text-zinc-500">
          {money(spend.spent_usd)} of {money(spend.limit_usd)} · {over ? `runs start again on ${day(spend.resets_on)}` : "runs pause once it's used up"}
        </span>
      </span>
      <span className="shrink-0 text-sm font-medium text-zinc-700">{over ? "Raise it" : "See"}</span>
    </a>
  );
}

/** This month's cost: the total against your limit, where it went, and the limit itself. */
export function SpendPanel({ token }: { token: string }) {
  const queryClient = useQueryClient();
  const spend = useSpend(token);
  const s = spend.data;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (usd: number | null) => builderApi.setSpendLimit(token, usd),
    onSuccess: (data) => {
      queryClient.setQueryData(spendKey, data);
      setEditing(false);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Couldn't save the limit."),
  });
  const submit = () => {
    const usd = Number(value);
    if (!value.trim() || !Number.isFinite(usd) || usd <= 0) {
      setError("Enter an amount in dollars, like 5.");
      return;
    }
    save.mutate(usd);
  };

  const share = s && s.limit_usd ? Math.min(1, s.spent_usd / s.limit_usd) : 0;
  const top = s?.by_item.filter((i) => i.cost_usd > 0) ?? [];

  return (
    <section id="spend" className="scroll-mt-6 overflow-hidden rounded-lg border border-zinc-200">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-100 px-4 py-3">
        <h2 className="text-base font-semibold text-zinc-900">Cost this month</h2>
        <span className="text-xs text-zinc-500">{s ? `${monthName(s.month_start)}, estimated` : ""}</span>
      </div>
      {!s ? (
        <div className="flex justify-center py-10">{spend.isError ? <p className="text-sm text-zinc-500">Couldn&apos;t load the cost.</p> : <Spinner className="h-5 w-5 text-zinc-400" />}</div>
      ) : (
        <div className="grid gap-6 p-4 md:grid-cols-2">
          {/* The total, against the limit */}
          <div className="space-y-3">
            <div>
              <p className="text-3xl font-semibold tabular-nums text-zinc-900">
                {money(s.spent_usd)}
                {s.limit_usd != null && <span className="text-base font-normal text-zinc-500"> of {money(s.limit_usd)}</span>}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {s.runs} run{s.runs === 1 ? "" : "s"} · last month {money(s.last_month_usd)}
                {s.unpriced_runs > 0 && ` · ${s.unpriced_runs} with no known price`}
              </p>
            </div>
            {s.limit_usd != null && (
              <div>
                <div
                  className="h-2 overflow-hidden rounded-full bg-zinc-100"
                  role="meter"
                  aria-label="Monthly limit used"
                  aria-valuemin={0}
                  aria-valuemax={s.limit_usd}
                  aria-valuenow={s.spent_usd}
                >
                  <div
                    className={cn("h-full rounded-full", s.status === "over" ? "bg-[var(--danger)]" : s.status === "near" ? "bg-amber-500" : "bg-[var(--accent)]")}
                    style={{ width: `${Math.max(share * 100, s.spent_usd > 0 ? 2 : 0)}%` }}
                  />
                </div>
                <p className={cn("mt-1.5 flex items-center gap-1 text-xs", s.status === "over" ? "text-red-600" : s.status === "near" ? "text-amber-700" : "text-zinc-500")}>
                  {s.status === "over" && <OctagonX className="h-3.5 w-3.5" />}
                  {s.status === "near" && <AlertTriangle className="h-3.5 w-3.5" />}
                  {s.status === "over"
                    ? `Used up: new runs wait until ${day(s.resets_on)} or a higher limit.`
                    : `${Math.round(share * 100)}% used${s.status === "near" ? ": runs pause once it's used up" : ""} · starts over on ${day(s.resets_on)}`}
                </p>
              </div>
            )}

            {editing ? (
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit();
                }}
              >
                <label className="block text-xs font-medium text-zinc-700" htmlFor="spend-limit">Monthly limit (USD)</label>
                <div className="flex flex-wrap gap-2">
                  <Input id="spend-limit" className="h-9 w-28" type="number" min="0.01" step="0.01" inputMode="decimal" autoFocus value={value} onChange={(e) => setValue(e.target.value)} placeholder="5" />
                  <Button type="submit" size="sm" className="h-9" disabled={save.isPending}>{save.isPending ? <Spinner className="h-4 w-4" /> : "Save"}</Button>
                  <Button type="button" size="sm" variant="outline" className="h-9" onClick={() => { setEditing(false); setError(null); }}>Cancel</Button>
                  {s.limit_usd != null && (
                    <Button type="button" size="sm" variant="ghost" className="h-9 text-zinc-500" disabled={save.isPending} onClick={() => save.mutate(null)}>No limit</Button>
                  )}
                </div>
                <p className="text-xs text-zinc-500">Once this month&apos;s runs cost this much, new runs (chat, Run, schedules) wait. A run already going finishes.</p>
                {error && <p className="text-xs text-red-600">{error}</p>}
              </form>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setValue(s.limit_usd != null ? String(s.limit_usd) : "");
                  setEditing(true);
                }}
              >
                {s.limit_usd != null ? "Change limit" : "Set a monthly limit"}
              </Button>
            )}
          </div>

          {/* Where it went */}
          <div>
            <p className="mb-2 text-xs font-medium text-zinc-500">Where it went</p>
            {top.length === 0 ? (
              <p className="text-sm text-zinc-500">Nothing spent yet this month.</p>
            ) : (
              <ol className="space-y-2.5">
                {top.map((i) => {
                  const part = s.spent_usd ? i.cost_usd / s.spent_usd : 0;
                  const name = (
                    <span className={cn("flex min-w-0 items-center gap-1.5 text-sm", i.exists ? "text-zinc-900" : "text-zinc-500")}>
                      <span className="truncate">{i.name}</span>
                      {i.kind === "workflow" && <Network className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="Workflow" />}
                      {!i.exists && <span className="shrink-0 text-xs">(deleted)</span>}
                    </span>
                  );
                  return (
                    <li key={`${i.kind}:${i.id}`}>
                      <div className="flex items-baseline justify-between gap-3">
                        {i.exists ? (
                          <Link href={`/user/executions?chat=${i.kind}:${encodeURIComponent(i.id)}&edit=1`} className="min-w-0 hover:underline" title={`Open ${i.name}`}>{name}</Link>
                        ) : (
                          name
                        )}
                        <span className="shrink-0 text-sm tabular-nums text-zinc-700">
                          {money(i.cost_usd)} <span className="text-xs text-zinc-500">· {i.runs} run{i.runs === 1 ? "" : "s"}</span>
                        </span>
                      </div>
                      <div className="mt-1 h-1 overflow-hidden rounded-full bg-zinc-100" aria-hidden>
                        <div className="h-full rounded-full bg-zinc-400" style={{ width: `${Math.max(part * 100, 2)}%` }} />
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
