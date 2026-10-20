"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Circle,
  Clock,
  Gauge,
  Loader2,
  MessageSquare,
  Network,
  ShieldAlert,
  Sparkles,
  Timer,
  Trophy,
  XCircle,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Avatar } from "@/components/builder/chat/chat-message";
import { ApprovalCard } from "@/components/builder/approval-card";
import { DailyBars, GOOD } from "@/components/charts/daily-bars";
import { builderApi } from "@/lib/builder/api";
import { vendorApi } from "@/lib/api";
import type { InsightsWindow, Run, RunStatus } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const WINDOW = 7;

/** Executions with this agent/workflow's chat open (and its editor, with ``edit``). */
const chatHref = (kind: "agent" | "workflow", id: string, edit = false) =>
  `/user/executions?chat=${kind}:${encodeURIComponent(id)}${edit ? "&edit=1" : "&tab=chat"}`;

function runHref(run: Run): string {
  const id = run.kind === "workflow" ? run.workflow_id : run.agent_id;
  return id ? chatHref(run.kind, id) : "/user/executions";
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
function ago(iso: string): string {
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const abs = Math.abs(s);
  if (abs < 60) return rtf.format(s, "second");
  if (abs < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}

const ms = (n: number) => (n >= 60000 ? `${Math.round(n / 60000)} min` : n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${n} ms`);

function duration(run: Run): string | null {
  if (!run.started_at || !run.finished_at) return null;
  return ms(new Date(run.finished_at).getTime() - new Date(run.started_at).getTime());
}

const STATUS: Record<RunStatus, { label: string; Icon: typeof CheckCircle2; className: string; pill: string }> = {
  succeeded: { label: "Succeeded", Icon: CheckCircle2, className: "text-emerald-600", pill: "bg-emerald-50 text-emerald-700" },
  failed: { label: "Failed", Icon: XCircle, className: "text-red-600", pill: "bg-red-50 text-red-700" },
  running: { label: "Running", Icon: Loader2, className: "text-sky-600 animate-spin", pill: "bg-sky-50 text-sky-700" },
  queued: { label: "Queued", Icon: Clock, className: "text-zinc-400", pill: "bg-zinc-100 text-zinc-600" },
  waiting: { label: "Waiting", Icon: ShieldAlert, className: "text-amber-600", pill: "bg-amber-50 text-amber-700" },
  cancelled: { label: "Cancelled", Icon: XCircle, className: "text-zinc-400", pill: "bg-zinc-100 text-zinc-600" },
};

/** How a number moved against the previous window, and whether that's good. */
type Delta = { text: string; up: boolean; good: boolean } | null;

function pctDelta(cur: number, prev: number, higherIsBetter: boolean): Delta {
  if (!prev) return null;
  const change = (cur - prev) / prev;
  if (Math.abs(change) < 0.005) return { text: "0%", up: true, good: true };
  return { text: `${Math.round(Math.abs(change) * 100)}%`, up: change > 0, good: change > 0 === higherIsBetter };
}

function ptsDelta(cur: InsightsWindow, prev: InsightsWindow): Delta {
  if (!prev.runs || !cur.runs) return null;
  const pts = (cur.success_rate - prev.success_rate) * 100;
  return { text: `${Math.abs(pts).toFixed(1)} pts`, up: pts >= 0, good: pts >= 0 };
}

export default function UserDashboard() {
  return (
    <ProtectedDashboard path="/user" title="Dashboard" description="Your AI workspace — build, deploy, and run agents." fullBleed>
      <Dashboard />
    </ProtectedDashboard>
  );
}

function Dashboard() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const user = useAuthStore((s) => s.user);
  const firstName = (user?.full_name || "").split(" ")[0] || "there";
  const team = user?.role === "tenant_user";

  const insights = useQuery({ queryKey: ["insights", WINDOW], queryFn: () => builderApi.insights(token, WINDOW), enabled: !!token, refetchInterval: 30000 });
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });
  const runs = useQuery({ queryKey: ["dashboard-runs"], queryFn: () => builderApi.listRuns(token, { limit: 50 }), enabled: !!token, refetchInterval: 15000 });
  const approvals = useQuery({ queryKey: ["builder-approvals"], queryFn: () => builderApi.listApprovals(token), enabled: !!token, refetchInterval: 15000 });
  const catalog = useQuery({ queryKey: ["catalog", token, ""], queryFn: () => vendorApi.getCatalog(token), enabled: !!token });

  const ins = insights.data;
  const agentList = agents.data ?? [];
  const workflowList = workflows.data ?? [];
  const runList = runs.data ?? [];
  const servers = catalog.data?.servers ?? [];
  const connected = servers.filter((s) => s.connected).length;
  const pending = approvals.data ?? [];
  const failedRecently = runList.filter((r) => r.status === "failed" && Date.now() - new Date(r.created_at).getTime() < 86400000).slice(0, 3);

  const projects = [
    ...agentList.map((a) => ({ kind: "agent" as const, id: a.id, name: a.name, updated: a.updated_at })),
    ...workflowList.map((w) => ({ kind: "workflow" as const, id: w.id, name: w.name, updated: w.updated_at })),
  ].sort((a, b) => b.updated.localeCompare(a.updated));

  const setupLoaded = agents.isSuccess && workflows.isSuccess && insights.isSuccess && catalog.isSuccess;
  const steps = [
    { done: connected > 0, title: "Connect an app", desc: "Gmail, Slack, a search tool… your agents work through them.", href: "/user/connectors", cta: "Connect" },
    { done: projects.length > 0, title: "Build your first agent", desc: "Describe what it should do and the AI sets it up.", href: "/user/agents", cta: "Build" },
    { done: (ins?.all_time.runs ?? 0) > 0, title: "Run it", desc: "Chat with it and watch every tool it uses.", href: "/user/executions", cta: "Open" },
  ];
  const setupLeft = setupLoaded && steps.some((s) => !s.done);

  const cur = ins?.current;
  const prev = ins?.previous;
  const chartDays = (ins?.series ?? []).map((d) => ({ date: d.date, good: d.succeeded, bad: d.failed }));

  return (
    <section className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Greeting */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm text-zinc-500">
            {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
            <span className="mx-2 text-zinc-400">·</span>
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", team ? "bg-sky-50 text-sky-700" : "bg-violet-50 text-violet-700")}>
              {team ? "Team workspace" : "Personal workspace"}
            </span>
          </p>
          <h1 className="mt-1 truncate text-2xl font-bold text-zinc-900 sm:text-3xl">
            {greeting()}, {firstName}
          </h1>
        </div>
        <div className="flex shrink-0 gap-2">
          <Link href="/user/executions" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 text-sm font-medium text-zinc-700 hover:bg-zinc-50">
            <MessageSquare className="h-4 w-4" /> Chat with an agent
          </Link>
          <Link href="/user/agents" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white shadow-sm hover:bg-indigo-700">
            <Sparkles className="h-4 w-4" /> Build with AI
          </Link>
        </div>
      </div>

      {/* Getting started */}
      {setupLeft && (
        <div className="rounded-xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-violet-50 p-4 sm:p-5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold text-zinc-900">Get started</h2>
            <span className="text-xs font-medium text-indigo-700">{steps.filter((s) => s.done).length} of {steps.length} done</span>
          </div>
          <ol className="mt-3 grid gap-3 md:grid-cols-3">
            {steps.map((s, i) => (
              <li key={s.title} className={cn("flex gap-3 rounded-lg border bg-white p-3", s.done ? "border-emerald-100" : "border-zinc-200")}>
                {s.done ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" /> : <Circle className="mt-0.5 h-5 w-5 shrink-0 text-zinc-400" />}
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm font-medium", s.done ? "text-zinc-400 line-through" : "text-zinc-900")}>
                    {i + 1}. {s.title}
                  </p>
                  <p className="mt-0.5 text-xs text-zinc-500">{s.desc}</p>
                  {!s.done && (
                    <Link href={s.href} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800">
                      {s.cta} <ArrowRight className="h-3 w-3" />
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Needs attention */}
      {(pending.length > 0 || failedRecently.length > 0) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 sm:p-5">
          <h2 className="flex items-center gap-2 font-semibold text-zinc-900">
            <AlertTriangle className="h-4 w-4 text-amber-600" /> Needs your attention
          </h2>
          <ul className="mt-3 grid gap-2 lg:grid-cols-2">
            {pending.slice(0, 4).map((a) => {
              const run = runList.find((r) => r.id === a.run_id);
              // Not in recent run history (a share-link / API run, or an old one): no chat to send them to, so decide here.
              if (!run) {
                return (
                  <li key={a.id} className="lg:col-span-2">
                    <ApprovalCard approval={a} token={token} onDone={() => void approvals.refetch()} />
                  </li>
                );
              }
              return (
                <li key={a.id}>
                  <Link href={run ? runHref(run) : "/user/executions"} className="flex items-center gap-3 rounded-lg border border-amber-100 bg-white p-3 hover:border-amber-300">
                    <ShieldAlert className="h-4 w-4 shrink-0 text-amber-600" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-zinc-900">{run?.name ? `${run.name} is waiting for you` : "A run is waiting for you"}</span>
                      <span className="block truncate text-xs text-zinc-500">
                        {a.payload.message || (a.tool_name ? `Approve “${a.payload.tool_name || a.tool_name}”` : "Approve or answer to continue")}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-medium text-amber-700">Review</span>
                  </Link>
                </li>
              );
            })}
            {failedRecently.map((r) => (
              <li key={r.id}>
                <Link href={runHref(r)} className="flex items-center gap-3 rounded-lg border border-red-100 bg-white p-3 hover:border-red-300">
                  <XCircle className="h-4 w-4 shrink-0 text-red-600" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-zinc-900">{r.name || "A run"} failed {ago(r.created_at)}</span>
                    <span className="block truncate text-xs text-zinc-500">{r.error || r.input?.text || "Open the chat to see what happened."}</span>
                  </span>
                  <span className="shrink-0 text-xs font-medium text-red-700">Open</span>
                </Link>
              </li>
            ))}
          </ul>
          {pending.length > 4 && <p className="mt-2 px-1 text-xs text-zinc-500">+ {pending.length - 4} more waiting</p>}
        </div>
      )}

      {/* KPIs: this week vs the one before */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
        <Kpi Icon={Activity} label="Runs" loading={!ins} value={cur ? String(cur.runs) : ""} delta={cur && prev ? pctDelta(cur.runs, prev.runs, true) : null} hint={`last ${WINDOW} days`} />
        <Kpi
          Icon={Gauge}
          label="Success rate"
          loading={!ins}
          value={cur ? (cur.runs ? `${Math.round(cur.success_rate * 100)}%` : "—") : ""}
          delta={cur && prev ? ptsDelta(cur, prev) : null}
          hint={cur?.runs ? `${cur.succeeded} of ${cur.succeeded + cur.failed} finished` : "no runs yet"}
          meter={cur?.runs ? cur.success_rate : undefined}
        />
        <Kpi
          Icon={Timer}
          label="Avg latency"
          loading={!ins}
          value={cur ? (cur.avg_latency_ms ? ms(cur.avg_latency_ms) : "—") : ""}
          delta={cur && prev && cur.avg_latency_ms ? pctDelta(cur.avg_latency_ms, prev.avg_latency_ms, false) : null}
          hint="start to answer"
        />
        <Kpi
          Icon={Bot}
          label="Active agents"
          loading={!ins || agents.isLoading || workflows.isLoading}
          value={cur ? String(cur.active) : ""}
          suffix={projects.length ? ` / ${projects.length}` : ""}
          hint={`ran in the last ${WINDOW} days`}
          href="/user/executions"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <DailyBars
            title="Runs"
            subtitle={`Last ${WINDOW * 2} days`}
            days={chartDays}
            goodLabel="Succeeded"
            badLabel="Failed"
            empty="No runs yet. Chat with an agent and its runs show up here."
          />
        </div>

        {/* Busiest */}
        <div className="rounded-xl border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 px-4 py-3 sm:px-5">
            <h2 className="flex items-center gap-2 font-semibold text-zinc-900"><Trophy className="h-4 w-4 text-amber-500" /> Busiest agents</h2>
          </div>
          {!ins ? (
            <SkeletonRows />
          ) : ins.busiest.length === 0 ? (
            <Empty Icon={Trophy} text="Your most used agents show up here once they've run." />
          ) : (
            <ol className="divide-y divide-zinc-100">
              {ins.busiest.map((b, i) => {
                const rate = b.runs ? b.succeeded / b.runs : 0;
                const body = (
                  <>
                    <span className="w-4 shrink-0 text-center text-xs font-semibold tabular-nums text-zinc-500">{i + 1}</span>
                    <Avatar name={b.name} size={32} />
                    <span className="min-w-0 flex-1">
                      <span className={cn("flex items-center gap-1.5 text-sm font-medium", b.exists ? "text-zinc-900" : "text-zinc-500")}>
                        <span className="truncate">{b.name}</span>
                        {b.kind === "workflow" && <Network className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="Workflow" />}
                        {!b.exists && <span className="shrink-0 text-[10px] font-normal">(deleted)</span>}
                      </span>
                      <span className="mt-1 flex items-center gap-2">
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-100" aria-hidden>
                          <span className="block h-full rounded-full" style={{ width: `${Math.round(rate * 100)}%`, background: GOOD }} />
                        </span>
                        <span className="shrink-0 text-[10px] tabular-nums text-zinc-500">{Math.round(rate * 100)}% ok</span>
                      </span>
                    </span>
                    <span className="shrink-0 text-right">
                      <span className="block text-sm font-semibold tabular-nums text-zinc-900">{b.runs}</span>
                      <span className="block text-[10px] text-zinc-500">runs</span>
                    </span>
                  </>
                );
                return (
                  <li key={`${b.kind}:${b.id}`}>
                    {b.exists ? (
                      <Link href={chatHref(b.kind, b.id)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50 sm:px-5" title={`Chat with ${b.name}`}>{body}</Link>
                    ) : (
                      <div className="flex items-center gap-3 px-4 py-3 sm:px-5">{body}</div>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>

      {/* Recent runs */}
      <div>
        <div className="rounded-xl border border-zinc-200 bg-white">
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 sm:px-5">
            <h2 className="font-semibold text-zinc-900">Recent runs</h2>
            <Link href="/user/executions" className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800">
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          {runs.isLoading ? (
            <SkeletonRows />
          ) : runList.length === 0 ? (
            <Empty Icon={Activity} text="No runs yet. Chat with an agent and its runs show up here." />
          ) : (
            <ul className="divide-y divide-zinc-100">
              {runList.slice(0, 7).map((r) => {
                const st = STATUS[r.status] ?? STATUS.queued;
                const took = duration(r);
                const name = r.name || (r.kind === "workflow" ? "Workflow" : "Agent");
                return (
                  <li key={r.id}>
                    <Link href={runHref(r)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50 sm:px-5">
                      <Avatar name={name} size={32} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-zinc-900">{r.input?.text || "—"}</span>
                        <span className="block truncate text-xs text-zinc-500">{name}</span>
                      </span>
                      <span className={cn("hidden shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium sm:inline-flex", st.pill)}>
                        <st.Icon className={cn("h-3 w-3", r.status === "running" && "animate-spin")} /> {st.label}
                      </span>
                      <st.Icon className={cn("h-4 w-4 shrink-0 sm:hidden", st.className)} aria-label={st.label} />
                      <span className="hidden w-14 shrink-0 text-right text-xs tabular-nums text-zinc-500 md:block">{took ?? "—"}</span>
                      <span className="w-20 shrink-0 text-right text-[11px] text-zinc-500">{ago(r.created_at)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

      </div>

    </section>
  );
}

function Kpi({
  Icon,
  label,
  value,
  suffix = "",
  delta = null,
  hint,
  loading,
  meter,
  href,
}: {
  Icon: typeof Bot;
  label: string;
  value: string;
  suffix?: string;
  delta?: Delta;
  hint: string;
  loading: boolean;
  /** 0–1: a thin bar under the value. */
  meter?: number;
  href?: string;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs font-medium text-zinc-500 sm:text-sm">
          <Icon className="h-4 w-4" /> {label}
        </span>
        {!loading && delta && (
          <span
            className={cn("inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular-nums", delta.good ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")}
            title={`vs the previous ${WINDOW} days`}
          >
            {delta.up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {delta.text}
          </span>
        )}
      </div>
      {loading ? (
        <>
          <div className="mt-2 h-8 w-16 animate-pulse rounded bg-zinc-100" />
          <div className="mt-2 h-3 w-28 animate-pulse rounded bg-zinc-100" />
        </>
      ) : (
        <>
          <p className="mt-2 text-2xl font-bold tabular-nums text-zinc-900 sm:text-3xl">
            {value}
            {suffix && <span className="text-base font-medium text-zinc-500">{suffix}</span>}
          </p>
          {meter !== undefined && (
            <span className="mt-2 block h-1 overflow-hidden rounded-full bg-zinc-100" aria-hidden>
              <span className="block h-full rounded-full" style={{ width: `${Math.round(meter * 100)}%`, background: GOOD }} />
            </span>
          )}
          <p className="mt-1.5 truncate text-[11px] text-zinc-500">
            {hint}
            {delta && <span className="hidden sm:inline"> · vs previous {WINDOW} days</span>}
          </p>
        </>
      )}
    </>
  );
  const cls = "rounded-xl border border-zinc-200 bg-white p-4 sm:p-5";
  return href ? <Link href={href} className={cn(cls, "transition-shadow hover:shadow-md")}>{body}</Link> : <div className={cls}>{body}</div>;
}

function SkeletonRows() {
  return (
    <ul className="divide-y divide-zinc-100" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <li key={i} className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <div className="h-8 w-8 animate-pulse rounded-full bg-zinc-100" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-1/3 animate-pulse rounded bg-zinc-100" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-100" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Empty({ Icon, text, cta }: { Icon: typeof Bot; text: string; cta?: { href: string; label: string } }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100">
        <Icon className="h-5 w-5 text-zinc-400" />
      </span>
      <p className="mt-3 text-sm text-zinc-500">{text}</p>
      {cta && (
        <Link href={cta.href} className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-800">
          {cta.label} <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      )}
    </div>
  );
}
