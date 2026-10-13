"use client";

import { useState } from "react";
import { CheckCircle2, Table2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

// Status colours (good / critical): always shown with an icon and a label, never alone.
export const GOOD = "#0ca30c";
export const CRITICAL = "#d03b3b";

export type DailyCount = { date: string; good: number; bad: number };

export const dayLabel = (date: string) =>
  new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });

/**
 * One stacked bar per day: the good part at the base, the bad part on top
 * (fixed order, 2px gap), a tooltip per day, and a table view of the same rows.
 */
export function DailyBars({
  title,
  subtitle,
  days,
  goodLabel = "Success",
  badLabel = "Error",
  empty,
  summary,
}: {
  title: string;
  subtitle: string;
  days: DailyCount[];
  goodLabel?: string;
  badLabel?: string;
  empty: string;
  /** A line under the title, e.g. "10 runs · 4 failed". */
  summary?: React.ReactNode;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const max = Math.max(1, ...days.map((d) => d.good + d.bad));
  const tick = Math.max(1, Math.ceil(max / 4));
  const top = tick * 4;
  const total = days.reduce((n, d) => n + d.good + d.bad, 0);
  const good = goodLabel.toLowerCase();
  const bad = badLabel.toLowerCase();

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 sm:p-5" aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-zinc-900">{title}</h2>
          <p className="text-xs text-zinc-500">{subtitle}</p>
          {summary && <p className="mt-1 text-xs text-zinc-600">{summary}</p>}
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-600">
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: GOOD }} /><CheckCircle2 className="h-3 w-3" /> {goodLabel}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CRITICAL }} /><XCircle className="h-3 w-3" /> {badLabel}</span>
          <button type="button" onClick={() => setAsTable((t) => !t)} className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 hover:bg-zinc-50 cursor-pointer" aria-pressed={asTable}>
            <Table2 className="h-3 w-3" /> {asTable ? "Chart" : "Table"}
          </button>
        </div>
      </div>

      {total === 0 ? (
        <div className="mt-4 flex h-40 items-center justify-center rounded-lg border border-dashed border-zinc-200 px-4 text-center text-sm text-zinc-500">{empty}</div>
      ) : asTable ? (
        <div className="mt-4 max-h-72 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-zinc-500">
                <th className="py-1 font-medium">Day</th>
                <th className="py-1 text-right font-medium">{goodLabel}</th>
                <th className="py-1 text-right font-medium">{badLabel}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {days.map((d) => (
                <tr key={d.date}>
                  <td className="py-1.5 text-zinc-700">{dayLabel(d.date)}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-900">{d.good}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-900">{d.bad}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4 flex gap-2">
          <div className="flex h-48 flex-col justify-between pb-5 text-right text-[10px] tabular-nums text-zinc-500" aria-hidden>
            {[4, 3, 2, 1, 0].map((i) => <span key={i} className="leading-none">{tick * i}</span>)}
          </div>
          <div className="relative min-w-0 flex-1">
            <div className="pointer-events-none absolute inset-x-0 top-0 flex h-[calc(100%-1.25rem)] flex-col justify-between" aria-hidden>
              {[0, 1, 2, 3, 4].map((i) => <div key={i} className="border-t border-zinc-100" />)}
            </div>
            <div className="relative flex h-48 items-stretch gap-1 sm:gap-1.5" role="img" aria-label={`${title}: ${total} in total`}>
              {days.map((d, i) => {
                const n = d.good + d.bad;
                return (
                  <div
                    key={d.date}
                    className="relative flex flex-1 flex-col justify-end pb-5 outline-none"
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(i)}
                    onBlur={() => setHover(null)}
                    tabIndex={0}
                    aria-label={`${dayLabel(d.date)}: ${d.good} ${good}, ${d.bad} ${bad}`}
                  >
                    <div
                      className={cn("flex w-full flex-col justify-end gap-[2px] transition-opacity", hover !== null && hover !== i && "opacity-60")}
                      style={{ height: `calc((100% - 1.25rem) * ${n / top})` }}
                    >
                      {d.bad > 0 && <div className="w-full rounded-t-[4px]" style={{ flexGrow: d.bad, background: CRITICAL, minHeight: 2 }} />}
                      {d.good > 0 && <div className={cn("w-full", d.bad > 0 ? "" : "rounded-t-[4px]")} style={{ flexGrow: d.good, background: GOOD, minHeight: 2 }} />}
                    </div>
                    <span className={cn("absolute bottom-0 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] text-zinc-500", i % 2 === (days.length - 1) % 2 ? "" : "hidden sm:inline")}>
                      {dayLabel(d.date)}
                    </span>
                    {hover === i && (
                      <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs shadow-lg">
                        <p className="font-medium text-zinc-900">{dayLabel(d.date)}</p>
                        <p className="flex items-center gap-1 text-zinc-600"><CheckCircle2 className="h-3 w-3" style={{ color: GOOD }} /> {d.good} {good}</p>
                        <p className="flex items-center gap-1 text-zinc-600"><XCircle className="h-3 w-3" style={{ color: CRITICAL }} /> {d.bad} {bad}</p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
