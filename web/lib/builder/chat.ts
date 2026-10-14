/**
 * Pure helpers for the playground chat (components/builder/chat): how long a
 * turn took, day dividers, avatars, starter prompts and the one-line summary
 * of what a run did. Covered by tests/chat.test.ts.
 */

import type { Run } from "@/lib/builder/types";

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || "?";
}

/** A stable hue per name, so each agent keeps its avatar colour. */
export function hueOf(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return h;
}

export function formatDuration(ms: number | null | undefined): string {
  const n = Math.max(0, Math.round(ms || 0));
  if (n < 1000) return `${n} ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(1)} s`;
  return `${Math.floor(n / 60_000)}m ${Math.round((n % 60_000) / 1000)}s`;
}

/** Start to finish of a run, or null while it hasn't both started and finished. */
export function runDurationMs(run: Pick<Run, "started_at" | "finished_at">): number | null {
  if (!run.started_at || !run.finished_at) return null;
  return Math.max(0, new Date(run.finished_at).getTime() - new Date(run.started_at).getTime());
}

export function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (d.toDateString() === now.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** "2 min ago" style, for the chat list. */
export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86_400) return `${Math.floor(s / 86_400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "Used 2 tools · 1 failed" — what a finished run did, or null if it used none. */
export function trailSummary(run: Pick<Run, "tool_calls">): string | null {
  const calls = run.tool_calls ?? [];
  if (!calls.length) return null;
  const failed = calls.filter((c) => c.is_error || c.status === "failed").length;
  const declined = calls.filter((c) => c.status === "declined" || c.status === "rejected").length;
  return [
    `Used ${calls.length} tool${calls.length === 1 ? "" : "s"}`,
    failed ? `${failed} failed` : null,
    declined ? `${declined} declined` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** "$0.0042", "$1.25" — enough digits for a single cheap run; null when unknown. */
export function formatCost(usd: number | null | undefined): string | null {
  if (usd == null) return null;
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

/** 950 -> "950", 12_400 -> "12.4k", 3_200_000 -> "3.2M". */
export function formatTokens(n: number | null | undefined): string {
  const v = Math.max(0, n || 0);
  if (v < 1000) return String(v);
  if (v < 1_000_000) return `${(v / 1000).toFixed(v < 10_000 ? 1 : 0).replace(/\.0$/, "")}k`;
  return `${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** The empty chat's suggested questions: the agent's own, else the general ones. */
export function startersFor(own: string[] | undefined): { label: string; prompt: string }[] {
  const mine = (own ?? []).map((s) => s.trim()).filter(Boolean);
  return mine.length ? mine.map((s) => ({ label: s, prompt: s })) : AGENT_STARTERS;
}

/** Suggested first messages for an agent. (A workflow gets none: whatever is
 *  sent is its input and starts a real run, so the person writes their own.) */
export const AGENT_STARTERS: { label: string; prompt: string }[] = [
  { label: "What can you do?", prompt: "What can you help me with, and which tools and data can you use?" },
  { label: "Show me an example", prompt: "Give me one practical example of a request I could ask you right now." },
  { label: "Summarise your rules", prompt: "Summarise how you work: your goal, your rules and what you will never do." },
];
