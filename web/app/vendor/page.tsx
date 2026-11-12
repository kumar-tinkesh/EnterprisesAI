"use client";

/** The platform admin's Overview: is the platform growing, is it working, and what needs them. */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Building2, PauseCircle, User, XCircle } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";
import { DailyBars } from "@/components/charts/daily-bars";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { Stat, Stats, type Delta } from "@/components/ui/stats";
import { useAuthStore } from "@/stores/auth-store";
import { api, vendorApi } from "@/lib/api";
import { appLabel } from "@/lib/connectors";
import { cn } from "@/lib/utils";

const DAYS = 14;

function delta(cur: number, prev: number, higherIsBetter = true): Delta {
  if (!prev) return null;
  const change = (cur - prev) / prev;
  if (Math.abs(change) < 0.005) return { text: "0%", up: true, good: true };
  return { text: `${Math.round(Math.abs(change) * 100)}%`, up: change > 0, good: change > 0 === higherIsBetter };
}
const money = (usd: number) => (usd === 0 ? "$0" : usd < 0.01 ? `$${usd.toFixed(3)}` : `$${usd.toFixed(2)}`);

export default function VendorOverview() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const overview = useQuery({
    queryKey: ["platform-overview", accessToken, DAYS],
    queryFn: () => vendorApi.platformOverview(accessToken, DAYS),
    enabled: !!accessToken,
    refetchInterval: 60000,
  });
  const { data: tenants = [] } = useQuery({ queryKey: ["vendor-tenants", accessToken], queryFn: () => api.getVendorTenants(accessToken), enabled: !!accessToken });
  const { data: servers = [] } = useQuery({ queryKey: ["vendor-mcp-servers", accessToken], queryFn: () => vendorApi.listMCPServers(accessToken), enabled: !!accessToken });

  const o = overview.data;
  const appsToFix = servers.filter((s) => s.status !== "VERIFIED" || !(s.bound_tools?.length ?? 0));
  const suspended = tenants.filter((t) => t.status !== "active");
  const failedRate = o && o.runs.current ? o.failed_runs.current / o.runs.current : 0;
  const names = Object.fromEntries(servers.map((s) => [s.id, appLabel(s.name, s.description).title]));
  const attention = [
    appsToFix.length > 0 && {
      key: "apps",
      href: "/vendor/tools",
      Icon: AlertTriangle,
      tone: "text-amber-600",
      title: `${appsToFix.length} app${appsToFix.length === 1 ? "" : "s"} can't be used yet`,
      text: `${appsToFix.slice(0, 4).map((s) => appLabel(s.name, s.description).title).join(", ")}: test them so people can connect.`,
    },
    o && o.failed_runs.current >= 3 && failedRate >= 0.2 && {
      key: "failed",
      href: "/vendor/accounts",
      Icon: XCircle,
      tone: "text-red-600",
      title: `${Math.round(failedRate * 100)}% of runs failed in the last ${DAYS} days`,
      text: `${o.failed_runs.current} of ${o.runs.current}. The busiest accounts below show where.`,
    },
    suspended.length > 0 && {
      key: "suspended",
      href: "/vendor/accounts?show=suspended",
      Icon: PauseCircle,
      tone: "text-zinc-500",
      title: `${suspended.length} suspended account${suspended.length === 1 ? "" : "s"}`,
      text: "Their people can't sign in until you turn them back on.",
    },
  ].filter(Boolean) as { key: string; href: string; Icon: typeof AlertTriangle; tone: string; title: string; text: string }[];

  return (
    <ProtectedDashboard path="/vendor" title="Overview" description="How the platform is doing, across every account.">
      <div className="mt-6 space-y-6">
        {attention.length > 0 && (
          <Panel title="Needs your attention">
            <ul className="divide-y divide-zinc-100">
              {attention.map((a) => (
                <li key={a.key}>
                  <Link href={a.href} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50">
                    <a.Icon className={cn("h-4 w-4 shrink-0", a.tone)} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-zinc-900">{a.title}</span>
                      <span className="block truncate text-xs text-zinc-500">{a.text}</span>
                    </span>
                    <span className="shrink-0 text-sm font-medium text-zinc-700">Open</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        <Stats>
          <Stat
            label="Active people"
            loading={!o}
            value={o ? String(o.active_people.current) : ""}
            suffix={o ? ` / ${o.people_total}` : ""}
            delta={o ? delta(o.active_people.current, o.active_people.previous) : null}
            sub={`signed in during the last ${DAYS} days`}
          />
          <Stat
            label="New people"
            loading={!o}
            value={o ? String(o.new_people.current) : ""}
            delta={o ? delta(o.new_people.current, o.new_people.previous) : null}
            sub={`joined in ${DAYS} days, vs the ${DAYS} before`}
            href="/vendor/accounts"
          />
          <Stat
            label="Agent runs"
            loading={!o}
            value={o ? String(o.runs.current) : ""}
            delta={o ? delta(o.runs.current, o.runs.previous) : null}
            sub={o && o.failed_runs.current ? `${o.failed_runs.current} failed` : "none failed"}
          />
          <Stat
            label="Cost this month"
            loading={!o}
            value={o ? money(o.cost_month_usd) : ""}
            sub={o ? `estimated · last month ${money(o.cost_last_month_usd)}` : ""}
          />
        </Stats>

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <DailyBars
              title="Agent runs"
              subtitle={`Every account, last ${DAYS * 2} days`}
              days={(o?.run_days ?? []).map((d) => ({ date: d.date, good: d.succeeded, bad: d.failed }))}
              goodLabel="Succeeded"
              badLabel="Failed"
              empty="No runs yet."
            />
          </div>
          <DailyBars
            title="Sign-ups"
            subtitle="Each week, last 8 weeks"
            days={(o?.signups_by_week ?? []).map((w) => ({ date: w.week_start, good: w.count, bad: 0 }))}
            goodLabel="New people"
            single
            period="Week of"
            empty="Nobody has joined yet."
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Most used apps" aside={<Link href="/vendor/tools" className="text-sm font-medium text-zinc-700 hover:text-zinc-900">All apps →</Link>}>
            {!o ? (
              <Skeleton />
            ) : o.top_apps.length === 0 ? (
              <Empty text="Nobody has connected an app yet." />
            ) : (
              <ol className="divide-y divide-zinc-100">
                {o.top_apps.map((a) => (
                  <li key={a.id} className="flex items-center gap-3 px-4 py-2.5">
                    <ConnectorIcon name={a.name} size="sm" />
                    <span className="min-w-0 flex-1 truncate text-sm text-zinc-900">{appLabel(a.name).title}</span>
                    <span className="shrink-0 text-right text-xs tabular-nums text-zinc-500">
                      {a.people} connected
                      <span className="block">{a.tool_calls} tool calls</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Panel>

          <Panel title="Busiest accounts" aside={<span className="text-xs text-zinc-500">this month</span>}>
            {!o ? (
              <Skeleton />
            ) : o.top_accounts.length === 0 ? (
              <Empty text="No runs this month yet." />
            ) : (
              <ol className="divide-y divide-zinc-100">
                {o.top_accounts.map((a) => (
                  <li key={a.id}>
                    <Link href={`/vendor/accounts?open=${encodeURIComponent(a.id)}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-zinc-50">
                      <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", a.is_personal ? "bg-purple-50 text-purple-700" : "bg-indigo-50 text-indigo-700")}>
                        {a.is_personal ? <User className="h-4 w-4" /> : <Building2 className="h-4 w-4" />}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm text-zinc-900">{a.name}</span>
                      <span className="shrink-0 text-right text-xs tabular-nums text-zinc-500">
                        {a.runs} runs
                        <span className="block">{money(a.cost_usd)}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        </div>

        <AuditLogsPanel title="Recent activity" limit={6} names={names} moreHref="/vendor/activity" compact />
      </div>
    </ProtectedDashboard>
  );
}

function Panel({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-100 px-4 py-3">
        <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Skeleton() {
  return (
    <ul className="divide-y divide-zinc-100" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <li key={i} className="space-y-2 px-4 py-3">
          <div className="h-3 w-1/3 animate-pulse rounded bg-zinc-100" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-100" />
        </li>
      ))}
    </ul>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="px-6 py-8 text-center text-sm text-zinc-500">{text}</p>;
}
