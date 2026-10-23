import Link from "next/link";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";

/** How a number moved against the previous window, and whether that's good. */
export type Delta = { text: string; up: boolean; good: boolean } | null;

/** A row of headline numbers in one bordered strip (2 across on phones, 4 on wide screens). */
export function Stats({ children }: { children: React.ReactNode }) {
  return <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-200 bg-[var(--border)] lg:grid-cols-4">{children}</dl>;
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
      <dt className="truncate text-sm text-zinc-500">{label}</dt>
      {loading ? (
        <dd className="mt-2 h-7 w-16 animate-pulse rounded bg-zinc-100" />
      ) : (
        <dd className="mt-1 flex flex-wrap items-baseline gap-x-2">
          <span className="text-2xl font-semibold tabular-nums text-zinc-900">
            {value}
            {suffix && <span className="text-base font-normal text-zinc-500">{suffix}</span>}
          </span>
          {delta && (
            <span className={cn("inline-flex items-center text-xs font-medium tabular-nums", delta.good ? "text-emerald-700" : "text-red-600")} title="vs the previous period">
              {delta.up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
              {delta.text}
            </span>
          )}
        </dd>
      )}
      {sub && <dd className="truncate text-xs text-zinc-500">{sub}</dd>}
    </>
  );
  const cls = "block bg-[var(--bg)] p-4";
  return href ? <Link href={href} className={cn(cls, "transition-colors hover:bg-[var(--hover)]")}>{body}</Link> : <div className={cls}>{body}</div>;
}
