"use client";

/** One account on the admin's Accounts page: its people, the apps they connected, and this month's use. */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, User, X } from "lucide-react";

import { ConnectorIcon } from "@/components/connections/connector-icon";
import { Spinner } from "@/components/ui/spinner";
import { vendorApi } from "@/lib/api";
import { appLabel } from "@/lib/connectors";
import { cn } from "@/lib/utils";

const money = (usd: number) => (usd === 0 ? "$0" : usd < 0.01 ? `$${usd.toFixed(3)}` : `$${usd.toFixed(2)}`);
const date = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
function ago(iso: string | null): string {
  if (!iso) return "Never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return m < 1 ? "just now" : `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

export function AccountPanel({ tenantId, accessToken, onClose }: { tenantId: string; accessToken: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["platform-account", tenantId], queryFn: () => vendorApi.platformAccount(accessToken, tenantId), enabled: !!accessToken });
  const a = q.data;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <aside className="flex h-full w-full flex-col border-l border-zinc-200 bg-[var(--surface-raised)] shadow-xl sm:w-[460px]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3 border-b border-zinc-200 p-4">
          <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", a?.is_personal ? "bg-purple-50 text-purple-700" : "bg-indigo-50 text-indigo-700")}>
            {a?.is_personal ? <User className="h-4 w-4" /> : <Building2 className="h-4 w-4" />}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-zinc-900">{a?.name ?? "Account"}</h2>
            {a && (
              <p className="text-xs text-zinc-500">
                {a.is_personal ? "Solo account" : "Organization"} · since {date(a.created_at)}
                {a.status !== "active" && <span className="ml-1.5 rounded-full bg-rose-50 px-2 py-0.5 text-rose-700">Suspended</span>}
              </p>
            )}
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-zinc-400 hover:text-zinc-700 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {q.isLoading && <div className="flex justify-center py-10"><Spinner className="h-5 w-5 text-zinc-400" /></div>}
          {q.isError && <p className="text-sm text-red-600">Couldn&apos;t load this account.</p>}
          {a && (
            <>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <Stat label="Runs this month" value={String(a.runs_month)} note={a.failed_month ? `${a.failed_month} failed` : undefined} />
                <Stat label="Cost this month" value={money(a.cost_month_usd)} note="estimated" />
                <Stat label="People" value={String(a.members.length)} />
                <Stat label="Last active" value={ago(a.last_active)} />
              </dl>

              <section>
                <h3 className="mb-2 text-sm font-medium text-zinc-900">People</h3>
                {a.members.length === 0 ? (
                  <p className="text-sm text-zinc-500">Nobody yet.</p>
                ) : (
                  <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                    {a.members.map((m) => (
                      <li key={m.id} className="flex items-center gap-2 px-3 py-2.5">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-medium text-zinc-700">
                          {(m.name || m.email).charAt(0).toUpperCase()}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-zinc-900">{m.name || m.email}</span>
                          <span className="block truncate text-xs text-zinc-500">{m.email} · joined {date(m.joined)}</span>
                        </span>
                        <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs", m.role === "tenant_admin" ? "bg-indigo-50 text-indigo-700" : "bg-zinc-100 text-zinc-600")}>
                          {m.role === "tenant_admin" ? "Admin" : "Member"}
                        </span>
                        {!m.is_active && <span className="shrink-0 rounded-full bg-rose-50 px-2 py-0.5 text-xs text-rose-700">Blocked</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="mb-2 text-sm font-medium text-zinc-900">Apps they connected</h3>
                {a.apps.length === 0 ? (
                  <p className="text-sm text-zinc-500">None yet.</p>
                ) : (
                  <ul className="flex flex-wrap gap-2">
                    {a.apps.map((app) => (
                      <li key={app.id} className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200 py-1 pl-1 pr-2.5 text-xs text-zinc-700">
                        <ConnectorIcon name={app.name} size="xs" />
                        {appLabel(app.name).title}
                        {!a.is_personal && app.people > 1 && <span className="text-zinc-400">· {app.people}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-2.5">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-0.5 font-medium tabular-nums text-zinc-900">{value}</dd>
      {note && <dd className="text-xs text-zinc-500">{note}</dd>}
    </div>
  );
}
