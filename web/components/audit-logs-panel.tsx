"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type AuditLog } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

/** What each audit action means, in words; the group a filter picks it by. */
const ACTIONS: Record<string, { text: string; group: "apps" | "people" | "access" }> = {
  login: { text: "Signed in", group: "people" },
  sso_login: { text: "Signed in with SSO", group: "people" },
  logout: { text: "Signed out", group: "people" },
  signup: { text: "New account created", group: "people" },
  bootstrap_admin: { text: "Admin account set up", group: "people" },
  "mcp_server.add": { text: "App added", group: "apps" },
  "mcp_server.create": { text: "App added", group: "apps" },
  "mcp_server.delete": { text: "App deleted", group: "apps" },
  "mcp_server.set_global": { text: "App's access changed", group: "access" },
  "mcp_server.test_connection": { text: "App tested", group: "apps" },
  "mcp_server.user_connect": { text: "Someone connected an app", group: "apps" },
  "tenant_resource.grant": { text: "App given to a tenant", group: "access" },
  "builder.tool_invoke": { text: "Tool run from the builder", group: "apps" },
};
// A session renewing itself every few minutes: real, but it buries everything else.
const NOISE = new Set(["refresh_token"]);

const FILTERS = [
  ["all", "All"],
  ["apps", "Apps"],
  ["people", "Sign-ins"],
  ["access", "Access"],
] as const;
type Filter = (typeof FILTERS)[number][0];

function when(ts: string | null): string {
  if (!ts) return "—";
  const m = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(ts).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "mcp_server:<id>" -> the app's name when known; "sso"/"auth" (the sign-in path) say nothing more. */
function about(resource: string, names: Record<string, string>): string {
  if (!resource || resource === "auth" || resource === "sso") return "";
  const [kind, id] = resource.split(":");
  if (id && names[id]) return names[id];
  // Only say "removed" once the app list is in; before that it's just not loaded yet.
  if (kind === "mcp_server") return Object.keys(names).length ? "an app that was since removed" : "an app";
  return resource;
}

/** The latest activity this admin may see (role-scoped server-side), in plain words. */
export function AuditLogsPanel({
  limit = 25,
  names = {},
  moreHref,
  title = "Activity",
  compact,
}: {
  limit?: number;
  names?: Record<string, string>;
  /** A "View all" link (the Overview's short list). */
  moreHref?: string;
  title?: string;
  /** No filters (a short list on an overview). */
  compact?: boolean;
}) {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const [filter, setFilter] = useState<Filter>("all");
  const [showNoise, setShowNoise] = useState(false);

  // More than shown: the session refreshes are dropped before the limit is applied.
  const [fetchSize, setFetchSize] = useState(Math.max(200, limit * 4));
  const [shownCount, setShownCount] = useState(limit);
  const { data: logs = [], isLoading, isError, isFetching } = useQuery({
    queryKey: ["audit-logs", accessToken, fetchSize],
    queryFn: () => api.getAuditLogs(accessToken, { limit: fetchSize }),
    enabled: !!accessToken,
  });

  const shown = logs
    .filter((l) => showNoise || !NOISE.has(l.action))
    .filter((l) => filter === "all" || ACTIONS[l.action]?.group === filter)
  ;
  const page = shown.slice(0, shownCount);
  const hidden = logs.filter((l) => NOISE.has(l.action)).length;

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 px-4 py-3">
        <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
        {moreHref && (
          <a href={moreHref} className="text-sm font-medium text-zinc-700 hover:text-zinc-900">
            View all →
          </a>
        )}
        {!compact && <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter activity">
          {FILTERS.map(([id, text]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs font-medium cursor-pointer",
                filter === id ? "border-[var(--accent)] bg-[var(--accent)] text-white" : "border-zinc-200 text-zinc-600 hover:bg-zinc-50",
              )}
            >
              {text}
            </button>
          ))}
        </div>}
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 px-4 py-6 text-sm text-zinc-500">
          <Spinner className="h-4 w-4" /> Loading…
        </div>
      ) : isError ? (
        <p className="px-4 py-6 text-sm text-red-600">Couldn&apos;t load the activity.</p>
      ) : page.length === 0 ? (
        <p className="px-4 py-6 text-sm text-zinc-500">Nothing here yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-100">
          {page.map((log: AuditLog) => {
            const what = ACTIONS[log.action]?.text ?? log.action.replace(/[._]/g, " ");
            const target = about(log.resource, names);
            return (
              <li key={log.id} className="flex items-start justify-between gap-4 px-4 py-2.5 text-sm">
                <span className="min-w-0">
                  <span className="text-zinc-900">{what}</span>
                  {target && <span className="text-zinc-500"> · {target}</span>}
                </span>
                <span className="shrink-0 text-right text-xs text-zinc-500" title={log.created_at ? new Date(log.created_at).toLocaleString() : undefined}>
                  {when(log.created_at)}
                  {log.ip_address && <span className="block text-zinc-400">{log.ip_address}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {!compact && (shown.length > shownCount || logs.length >= fetchSize) && (
        <button
          type="button"
          disabled={isFetching}
          onClick={() => {
            setShownCount((n) => n + limit);
            if (shown.length <= shownCount + limit) setFetchSize((n) => n * 2);
          }}
          className="w-full border-t border-zinc-100 px-4 py-2 text-center text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 cursor-pointer"
        >
          {isFetching ? "Loading…" : "Show more"}
        </button>
      )}
      {!compact && hidden > 0 && (
        <button
          type="button"
          onClick={() => setShowNoise((s) => !s)}
          className="w-full border-t border-zinc-100 px-4 py-2 text-left text-xs text-zinc-500 hover:text-zinc-900 cursor-pointer"
        >
          {showNoise ? "Hide session refreshes" : `${hidden} session refreshes hidden · show them`}
        </button>
      )}
    </section>
  );
}
