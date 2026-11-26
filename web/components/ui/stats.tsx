import Link from "next/link";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";

/** How a number moved against the previous window, and whether that's good. */
export type Delta = { text: string; up: boolean; good: boolean } | null;

/** A row of headline numbers in one bordered strip (2 across on phones, 4 on wide screens). */
export function Stats({ children }: { children: React.ReactNode }) {
  return <dl className="animate-fade-up grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-white/10 bg-[var(--border)] shadow-sm lg:grid-cols-4">{children}</dl>;
}

export function Stat({
  label,
  value,
  suffix,
  sub,
  delta,
  loading,
  href,
}: {
  label: string;
  value: string;
  suffix?: string;
  sub?: string;
  delta?: Delta;
  loading?: boolean;
  href?: string;
}) {
  const body = (
    <>
      <dt className="truncate text-xs font-medium uppercase tracking-wider text-zinc-400">{label}</dt>
      {loading ? (
        <dd className="mt-2 h-7 w-20 animate-pulse rounded-md bg-white/[0.06]" />
      ) : (
        <dd className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-2xl font-semibold tracking-tight tabular-nums text-zinc-100">
            {value}
            {suffix && <span className="text-base font-normal text-zinc-400">{suffix}</span>}
          </span>
          {delta && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular-nums",
                delta.good ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400",
              )}
              title="vs the previous period"
            >
              {delta.up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {delta.text}
            </span>
          )}
        </dd>
      )}
      {sub && <dd className="mt-1 truncate text-xs text-zinc-500">{sub}</dd>}
    </>
  );
  const cls = "block bg-[var(--surface)] p-4 transition-colors duration-150";
  return href ? <Link href={href} className={cn(cls, "hover:bg-[var(--surface-raised)]")}>{body}</Link> : <div className={cn(cls, "hover:bg-white/[0.015]")}>{body}</div>;
}
