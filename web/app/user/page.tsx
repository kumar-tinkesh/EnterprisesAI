"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Circle, Clock, Loader2, MessageSquare, Network, Plus, ShieldAlert, XCircle } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { ApprovalCard } from "@/components/builder/approval-card";
import { DailyBars } from "@/components/charts/daily-bars";
import { Stat, Stats, type Delta } from "@/components/ui/stats";
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

const STATUS: Record<RunStatus, { label: string; Icon: typeof CheckCircle2; className: string }> = {
  succeeded: { label: "Succeeded", Icon: CheckCircle2, className: "text-emerald-700" },
  failed: { label: "Failed", Icon: XCircle, className: "text-red-600" },
  running: { label: "Running", Icon: Loader2, className: "text-indigo-600 animate-spin" },
  queued: { label: "Queued", Icon: Clock, className: "text-zinc-400" },
  waiting: { label: "Waiting", Icon: ShieldAlert, className: "text-amber-700" },
  cancelled: { label: "Cancelled", Icon: XCircle, className: "text-zinc-400" },
};

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
    <section className="mx-auto max-w-6xl space-y-8 px-4 py-6 sm:px-8 sm:py-8">
      {/* Greeting */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold text-zinc-900">
            {greeting()}, {firstName}
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Link href="/user/executions" className="inline-flex h-9 items-center gap-2 rounded-md border border-[var(--border-strong)] px-3 text-sm font-medium text-zinc-900 hover:bg-zinc-50">
            <MessageSquare className="h-4 w-4" /> Chat
          </Link>
          <Link href="/user/agents" className="inline-flex h-9 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white hover:bg-[var(--accent-hover)]">
            <Plus className="h-4 w-4" /> New agent
          </Link>
        </div>
      </div>

      {/* Getting started */}
      {setupLeft && (
        <Panel title="Get started" aside={`${steps.filter((s) => s.done).length} of ${steps.length} done`}>
          <ol className="divide-y divide-zinc-100">
            {steps.map((s) => (
              <li key={s.title} className="flex items-center gap-3 px-4 py-3">
                {s.done ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-700" /> : <Circle className="h-5 w-5 shrink-0 text-zinc-400" />}
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm font-medium", s.done ? "text-zinc-500 line-through" : "text-zinc-900")}>{s.title}</p>
                  <p className="text-xs text-zinc-500">{s.desc}</p>
                </div>
                {!s.done && (
                  <Link href={s.href} className="inline-flex h-8 shrink-0 items-center rounded-md border border-[var(--border-strong)] px-3 text-sm font-medium text-zinc-900 hover:bg-zinc-50">
                    {s.cta}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Panel>
      )}

      {/* Needs attention */}
      {(pending.length > 0 || failedRecently.length > 0) && (
        <Panel title="Needs your attention" aside={pending.length > 4 ? `+ ${pending.length - 4} more waiting` : undefined}>
          <ul className="divide-y divide-zinc-100">
            {pending.slice(0, 4).map((a) => {
              const run = runList.find((r) => r.id === a.run_id);
              // Not in recent run history (a share-link / API run, or an old one): no chat to send them to, so decide here.
              if (!run) {
                return (
                  <li key={a.id} className="p-3">
                    <ApprovalCard approval={a} token={token} onDone={() => void approvals.refetch()} />
                  </li>
                );
              }
              return (
                <li key={a.id}>
                  <Link href={runHref(run)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50">
                    <ShieldAlert className="h-4 w-4 shrink-0 text-amber-700" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-zinc-900">{run.name ? `${run.name} is waiting for you` : "A run is waiting for you"}</span>
                      <span className="block truncate text-xs text-zinc-500">
                        {a.payload.message || (a.tool_name ? `Approve “${a.payload.tool_name || a.tool_name}”` : "Approve or answer to continue")}
                      </span>
                    </span>
                    <span className="shrink-0 text-sm font-medium text-zinc-700">Review</span>
                  </Link>
                </li>
              );
            })}
            {failedRecently.map((r) => (
              <li key={r.id}>
                <Link href={runHref(r)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50">
                  <XCircle className="h-4 w-4 shrink-0 text-red-600" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-zinc-900">{r.name || "A run"} failed {ago(r.created_at)}</span>
                    <span className="block truncate text-xs text-zinc-500">{r.error || r.input?.text || "Open the chat to see what happened."}</span>
                  </span>
                  <span className="shrink-0 text-sm font-medium text-zinc-700">Open</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {/* KPIs: this week vs the one before */}
      <Stats>
        <Stat label="Runs" loading={!ins} value={cur ? String(cur.runs) : ""} delta={cur && prev ? pctDelta(cur.runs, prev.runs, true) : null} sub={`last ${WINDOW} days`} />
        <Stat
          label="Success rate"
          loading={!ins}
          value={cur ? (cur.runs ? `${Math.round(cur.success_rate * 100)}%` : "—") : ""}
          delta={cur && prev ? ptsDelta(cur, prev) : null}
          sub={cur?.runs ? `${cur.succeeded} of ${cur.succeeded + cur.failed} finished` : "no runs yet"}
        />
        <Stat
          label="Avg time"
          loading={!ins}
          value={cur ? (cur.avg_latency_ms ? ms(cur.avg_latency_ms) : "—") : ""}
          delta={cur && prev && cur.avg_latency_ms ? pctDelta(cur.avg_latency_ms, prev.avg_latency_ms, false) : null}
          sub="start to answer"
        />
        <Stat
          label="Active agents"
          loading={!ins || agents.isLoading || workflows.isLoading}
          value={cur ? String(cur.active) : ""}
          suffix={projects.length ? ` / ${projects.length}` : ""}
          sub={`ran in the last ${WINDOW} days`}
          href="/user/executions"
        />
      </Stats>

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

        <Panel title="Most used">
          {!ins ? (
            <SkeletonRows />
          ) : ins.busiest.length === 0 ? (
            <Empty text="Your most used agents show up here once they've run." />
          ) : (
            <ol className="divide-y divide-zinc-100">
              {ins.busiest.map((b) => {
                const rate = b.runs ? Math.round((b.succeeded / b.runs) * 100) : 0;
                const body = (
                  <>
                    <span className="min-w-0 flex-1">
                      <span className={cn("flex items-center gap-1.5 text-sm font-medium", b.exists ? "text-zinc-900" : "text-zinc-500")}>
                        <span className="truncate">{b.name}</span>
                        {b.kind === "workflow" && <Network className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="Workflow" />}
                        {!b.exists && <span className="shrink-0 text-xs font-normal">(deleted)</span>}
                      </span>
                      <span className="block text-xs text-zinc-500">{rate}% succeeded</span>
                    </span>
                    <span className="shrink-0 text-sm tabular-nums text-zinc-700">{b.runs} runs</span>
                  </>
                );
                return (
                  <li key={`${b.kind}:${b.id}`}>
                    {b.exists ? (
                      <Link href={chatHref(b.kind, b.id)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50" title={`Chat with ${b.name}`}>{body}</Link>
                    ) : (
                      <div className="flex items-center gap-3 px-4 py-3">{body}</div>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>
      </div>

      {/* Recent runs */}
      <Panel
        title="Recent runs"
        aside={
          <Link href="/user/executions" className="inline-flex items-center gap-1 text-sm font-medium text-zinc-700 hover:text-zinc-900">
            View all <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        }
      >
        {runs.isLoading ? (
          <SkeletonRows />
        ) : runList.length === 0 ? (
          <Empty text="No runs yet. Chat with an agent and its runs show up here." />
        ) : (
          <ul className="divide-y divide-zinc-100">
            {runList.slice(0, 7).map((r) => {
              const st = STATUS[r.status] ?? STATUS.queued;
              const took = duration(r);
              const name = r.name || (r.kind === "workflow" ? "Workflow" : "Agent");
              return (
                <li key={r.id}>
                  <Link href={runHref(r)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50">
                    <st.Icon className={cn("h-4 w-4 shrink-0", st.className)} aria-label={st.label} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-zinc-900">{r.input?.text || "—"}</span>
                      <span className="block truncate text-xs text-zinc-500">{name} · {st.label}</span>
                    </span>
                    <span className="hidden w-14 shrink-0 text-right text-xs tabular-nums text-zinc-500 md:block">{took ?? "—"}</span>
                    <span className="w-24 shrink-0 text-right text-xs text-zinc-500">{ago(r.created_at)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </section>
  );
}

/** A bordered block with a heading row: the dashboard's one container. */
function Panel({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-lg border border-zinc-200">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-100 px-4 py-3">
        <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
        {typeof aside === "string" ? <span className="text-xs text-zinc-500">{aside}</span> : aside}
      </div>
      {children}
    </section>
  );
}

function SkeletonRows() {
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
  return <p className="px-6 py-10 text-center text-sm text-zinc-500">{text}</p>;
}
