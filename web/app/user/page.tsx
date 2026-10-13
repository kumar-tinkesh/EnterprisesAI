"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  MessageSquare,
  Network,
  Pencil,
  Plug,
  ShieldAlert,
  Sparkles,
  XCircle,
  Zap,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Avatar } from "@/components/builder/chat/chat-message";
import { builderApi } from "@/lib/builder/api";
import { knowledgeApi, vendorApi } from "@/lib/api";
import type { Run, RunStatus } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

/** Executions with this agent/workflow's chat open (and its editor, with ``edit``). */
const chatHref = (kind: "agent" | "workflow", id: string, edit = false) =>
  `/user/executions?chat=${kind}:${encodeURIComponent(id)}${edit ? "&edit=1" : ""}`;

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

function duration(run: Run): string | null {
  if (!run.started_at || !run.finished_at) return null;
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  return ms < 1000 ? `${ms} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 60000)} min`;
}

const isToday = (iso: string) => new Date(iso).toDateString() === new Date().toDateString();

const STATUS: Record<RunStatus, { label: string; Icon: typeof CheckCircle2; className: string }> = {
  succeeded: { label: "Succeeded", Icon: CheckCircle2, className: "text-emerald-600" },
  failed: { label: "Failed", Icon: XCircle, className: "text-red-600" },
  running: { label: "Running", Icon: Loader2, className: "text-sky-600 animate-spin" },
  queued: { label: "Queued", Icon: Clock, className: "text-zinc-400" },
  waiting: { label: "Waiting for you", Icon: ShieldAlert, className: "text-amber-600" },
  cancelled: { label: "Cancelled", Icon: XCircle, className: "text-zinc-400" },
};

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

  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });
  const runs = useQuery({ queryKey: ["dashboard-runs"], queryFn: () => builderApi.listRuns(token, { limit: 100 }), enabled: !!token, refetchInterval: 15000 });
  const approvals = useQuery({ queryKey: ["builder-approvals"], queryFn: () => builderApi.listApprovals(token), enabled: !!token, refetchInterval: 15000 });
  const catalog = useQuery({ queryKey: ["catalog", token, ""], queryFn: () => vendorApi.getCatalog(token), enabled: !!token });
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });

  const agentList = agents.data ?? [];
  const workflowList = workflows.data ?? [];
  const runList = runs.data ?? [];
  const servers = catalog.data?.servers ?? [];
  const connected = servers.filter((s) => s.connected).length;
  const today = runList.filter((r) => isToday(r.created_at));
  const todayOk = today.filter((r) => r.status === "succeeded").length;
  const todayFailed = today.filter((r) => r.status === "failed").length;
  const docs = (kbs.data ?? []).reduce((n, kb) => n + kb.document_count, 0);

  const pending = approvals.data ?? [];
  const failed = runList.filter((r) => r.status === "failed" && Date.now() - new Date(r.created_at).getTime() < 86400000).slice(0, 3);

  const projects = [
    ...agentList.map((a) => ({ kind: "agent" as const, id: a.id, name: a.name, sub: a.goal, updated: a.updated_at })),
    ...workflowList.map((w) => ({ kind: "workflow" as const, id: w.id, name: w.name, sub: w.description || `${w.node_count} steps`, updated: w.updated_at })),
  ].sort((a, b) => b.updated.localeCompare(a.updated));

  const setupLoaded = agents.isSuccess && workflows.isSuccess && runs.isSuccess && catalog.isSuccess;
  const steps = [
    { done: connected > 0, title: "Connect an app", desc: "Gmail, Slack, a search tool… your agents work through them.", href: "/user/connectors", cta: "Connect" },
    { done: projects.length > 0, title: "Build your first agent", desc: "Describe what it should do and the AI sets it up.", href: "/user/agents", cta: "Build" },
    { done: runList.length > 0, title: "Run it", desc: "Chat with it and watch every tool it uses.", href: "/user/executions", cta: "Open" },
  ];
  const setupLeft = setupLoaded && steps.some((s) => !s.done);

  return (
    <section className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6 lg:p-8">
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

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
        <Stat
          href="/user/executions"
          Icon={Bot}
          tone="indigo"
          label="Agents & workflows"
          loading={agents.isLoading || workflows.isLoading}
          value={projects.length}
          sub={`${agentList.length} agent${agentList.length === 1 ? "" : "s"} · ${workflowList.length} workflow${workflowList.length === 1 ? "" : "s"}`}
        />
        <Stat
          href="/user/executions"
          Icon={Zap}
          tone="amber"
          label="Runs today"
          loading={runs.isLoading}
          value={today.length}
          sub={today.length ? `${todayOk} succeeded${todayFailed ? ` · ${todayFailed} failed` : ""}` : "Nothing run yet today"}
        />
        <Stat
          href="/user/connectors"
          Icon={Plug}
          tone="sky"
          label="Connectors"
          loading={catalog.isLoading}
          value={connected}
          suffix={servers.length ? ` / ${servers.length}` : ""}
          sub={connected ? "connected and ready" : "None connected yet"}
        />
        <Stat
          href="/user/knowledge"
          Icon={Brain}
          tone="violet"
          label="Knowledge docs"
          loading={kbs.isLoading}
          value={docs}
          sub={`in ${(kbs.data ?? []).length} knowledge base${(kbs.data ?? []).length === 1 ? "" : "s"}`}
        />
      </div>

      {/* Needs attention */}
      {(pending.length > 0 || failed.length > 0) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 sm:p-5">
          <h2 className="flex items-center gap-2 font-semibold text-zinc-900">
            <AlertTriangle className="h-4 w-4 text-amber-600" /> Needs your attention
          </h2>
          <ul className="mt-3 space-y-2">
            {pending.slice(0, 3).map((a) => {
              const run = runList.find((r) => r.id === a.run_id);
              return (
                <li key={a.id}>
                  <Link href={run ? runHref(run) : "/user/executions"} className="flex items-center gap-3 rounded-lg border border-amber-100 bg-white p-3 hover:border-amber-300">
                    <ShieldAlert className="h-4 w-4 shrink-0 text-amber-600" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-zinc-900">
                        {run?.name ? `${run.name} is waiting for you` : "A run is waiting for you"}
                      </span>
                      <span className="block truncate text-xs text-zinc-500">
                        {a.payload.message || (a.tool_name ? `Approve “${a.payload.tool_name || a.tool_name}”` : "Approve or answer to continue")}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-medium text-amber-700">Review</span>
                  </Link>
                </li>
              );
            })}
            {pending.length > 3 && <li className="px-1 text-xs text-zinc-500">+ {pending.length - 3} more waiting</li>}
            {failed.map((r) => (
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
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Your agents */}
        <div className="rounded-xl border border-zinc-200 bg-white lg:col-span-3">
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 sm:px-5">
            <h2 className="font-semibold text-zinc-900">Your agents & workflows</h2>
            <Link href="/user/executions" className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800">
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          {agents.isLoading || workflows.isLoading ? (
            <SkeletonRows />
          ) : projects.length === 0 ? (
            <Empty Icon={Bot} text="No agents yet." cta={{ href: "/user/agents", label: "Build one with AI" }} />
          ) : (
            <ul className="divide-y divide-zinc-100">
              {projects.slice(0, 6).map((p) => (
                <li key={`${p.kind}:${p.id}`} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                  <Avatar name={p.name} size={36} />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-medium text-zinc-900">{p.name}</span>
                      {p.kind === "workflow" && <Network className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="Workflow" />}
                    </p>
                    <p className="truncate text-xs text-zinc-500">{p.sub}</p>
                  </div>
                  <span className="hidden shrink-0 text-[11px] text-zinc-400 sm:block">{ago(p.updated)}</span>
                  <Link href={chatHref(p.kind, p.id)} title={`Chat with ${p.name}`} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-zinc-200 px-2.5 text-xs font-medium text-zinc-700 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700">
                    <MessageSquare className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Chat</span>
                  </Link>
                  <Link href={chatHref(p.kind, p.id, true)} aria-label={`Edit ${p.name}`} title="Edit" className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
                    <Pencil className="h-3.5 w-3.5" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Recent activity */}
        <div className="rounded-xl border border-zinc-200 bg-white lg:col-span-2">
          <div className="border-b border-zinc-100 px-4 py-3 sm:px-5">
            <h2 className="font-semibold text-zinc-900">Recent activity</h2>
          </div>
          {runs.isLoading ? (
            <SkeletonRows />
          ) : runList.length === 0 ? (
            <Empty Icon={Zap} text="No runs yet. Chat with an agent and its runs show up here." />
          ) : (
            <ul className="divide-y divide-zinc-100">
              {runList.slice(0, 8).map((r) => {
                const st = STATUS[r.status] ?? STATUS.queued;
                const took = duration(r);
                return (
                  <li key={r.id}>
                    <Link href={runHref(r)} className="flex items-start gap-3 px-4 py-3 hover:bg-zinc-50 sm:px-5" title={st.label}>
                      <st.Icon className={cn("mt-0.5 h-4 w-4 shrink-0", st.className)} aria-label={st.label} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-zinc-900">{r.name || (r.kind === "workflow" ? "Workflow" : "Agent")}</span>
                        <span className="block truncate text-xs text-zinc-500">{r.input?.text || "—"}</span>
                      </span>
                      <span className="shrink-0 text-right text-[11px] text-zinc-400">
                        {ago(r.created_at)}
                        {took && <span className="block">{took}</span>}
                      </span>
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

const TONES = {
  indigo: "bg-indigo-50 text-indigo-600",
  amber: "bg-amber-50 text-amber-600",
  sky: "bg-sky-50 text-sky-600",
  violet: "bg-violet-50 text-violet-600",
};

function Stat({
  href,
  Icon,
  tone,
  label,
  value,
  suffix = "",
  sub,
  loading,
}: {
  href: string;
  Icon: typeof Bot;
  tone: keyof typeof TONES;
  label: string;
  value: number;
  suffix?: string;
  sub: string;
  loading: boolean;
}) {
  return (
    <Link href={href} className="group rounded-xl border border-zinc-200 bg-white p-4 transition-all hover:-translate-y-0.5 hover:shadow-md sm:p-5">
      <div className="flex items-center justify-between">
        <span className={cn("flex h-9 w-9 items-center justify-center rounded-lg", TONES[tone])}>
          <Icon className="h-4 w-4" />
        </span>
        <ArrowRight className="h-4 w-4 text-zinc-400 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-500" />
      </div>
      <p className="mt-3 text-xs font-medium text-zinc-500 sm:text-sm">{label}</p>
      {loading ? (
        <>
          <div className="mt-1 h-8 w-14 animate-pulse rounded bg-zinc-100" />
          <div className="mt-2 h-3 w-24 animate-pulse rounded bg-zinc-100" />
        </>
      ) : (
        <>
          <p className="mt-0.5 text-2xl font-bold text-zinc-900 sm:text-3xl">
            {value}
            {suffix && <span className="text-base font-medium text-zinc-400">{suffix}</span>}
          </p>
          <p className="mt-1 truncate text-[11px] text-zinc-500 sm:text-xs">{sub}</p>
        </>
      )}
    </Link>
  );
}

function SkeletonRows() {
  return (
    <ul className="divide-y divide-zinc-100" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <li key={i} className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <div className="h-9 w-9 animate-pulse rounded-full bg-zinc-100" />
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
