"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  CalendarClock,
  Globe,
  Loader2,
  MessageSquare,
  Network,
  Pencil,
  Plus,
  Search,
  ShieldAlert,
  Trash2,
  Users,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { type ChatTarget } from "@/components/builder/chat/chat-panel";
import { ProjectDetail, type DetailTab } from "@/components/builder/project-detail";
import { Avatar } from "@/components/builder/chat/chat-message";
import { AgentEditor } from "@/components/builder/agent-editor";
import { WorkflowEditor } from "@/components/builder/workflow-editor";
import { AgentWizardHost } from "@/components/builder/agent-wizard/agent-wizard";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { vendorApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { serverIdOf } from "@/lib/builder/graph";
import type { OverviewItem } from "@/lib/builder/types";
import { useBuilderActions, type BuildMode, type BuildTarget } from "@/lib/builder/use-builder-actions";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const TAB_KEY = "projects.tab"; // kept so the saved tab survives the rename
const WINDOW = 7;

/** ?chat=agent:<id> / ?chat=workflow:<id> — the one open beside the list; &tab=… — which of its views; &edit=1 — its canvas in place of the list. */
function chatFromUrl(): ChatTarget | null {
  if (typeof window === "undefined") return null;
  const [kind, id] = (new URLSearchParams(window.location.search).get("chat") ?? "").split(":");
  return (kind === "agent" || kind === "workflow") && id ? { kind, id } : null;
}

const DETAIL_TABS: DetailTab[] = ["overview", "chat", "simulate", "health"];
function tabFromUrl(): DetailTab {
  const t = new URLSearchParams(window.location.search).get("tab");
  return DETAIL_TABS.includes(t as DetailTab) ? (t as DetailTab) : "overview";
}

function setChatUrl(target: ChatTarget | null, editing = false, detail: DetailTab = "overview") {
  const url = new URL(window.location.href);
  if (target) url.searchParams.set("chat", `${target.kind}:${target.id}`);
  else url.searchParams.delete("chat");
  if (target && detail !== "overview") url.searchParams.set("tab", detail);
  else url.searchParams.delete("tab");
  if (target && editing) url.searchParams.set("edit", "1");
  else url.searchParams.delete("edit");
  window.history.replaceState(null, "", url);
}

function ago(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** "0 9 * * *" → "daily 09:00"; anything less regular stays as the cron. */
function cronLabel(cron: string): string {
  const [m, h, dom, mon, dow] = cron.trim().split(/\s+/);
  const at = /^\d+$/.test(m) && /^\d+$/.test(h) ? `${h.padStart(2, "0")}:${m.padStart(2, "0")}` : null;
  if (at && dom === "*" && mon === "*" && dow === "*") return `daily ${at}`;
  if (at && dom === "*" && mon === "*" && dow === "1-5") return `weekdays ${at}`;
  if (at && dom === "*" && mon === "*" && /^\d$/.test(dow)) return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][Number(dow) % 7]} ${at}`;
  if (m === "0" && h === "*") return "hourly";
  return cron;
}

const HEALTH: Record<OverviewItem["health_status"], { label: string; dot: string; text: string; order: number }> = {
  needs_attention: { label: "Needs attention", dot: "bg-amber-500", text: "text-amber-700", order: 0 },
  testing: { label: "Testing", dot: "bg-amber-500", text: "text-amber-700", order: 1 },
  not_tested: { label: "Not tested", dot: "bg-zinc-400", text: "text-zinc-500", order: 2 },
  production_ready: { label: "Ready", dot: "bg-emerald-500", text: "text-emerald-700", order: 3 },
};

const FILTERS = {
  all: "All",
  attention: "Needs attention",
  live: "Running now",
  never: "Never run",
  scheduled: "Scheduled",
  published: "Published",
  mine: "Mine",
  shared: "Shared with me",
} as const;
type Filter = keyof typeof FILTERS;

const SORTS = { last_run: "Last run", runs: "Most runs", health: "Health", name: "Name" } as const;
type Sort = keyof typeof SORTS;

type Item = {
  kind: BuildMode;
  id: string;
  name: string;
  sub: string;
  updated: string;
  canManage: boolean;
  mine: boolean;
  servers: string[];
  stats: OverviewItem | undefined;
};

export default function ExecutionsPage() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const userId = useAuthStore((s) => s.user?.id);
  const [tab, setTab] = useState<BuildMode>("agent");
  const [chat, setChat] = useState<ChatTarget | null>(null);
  // The selected one is open on the canvas, in place of the list.
  const [editing, setEditing] = useState(false);
  const [detail, setDetail] = useState<DetailTab>("overview");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("last_run");
  const { createBlank, remove, error, setError } = useBuilderActions();

  useEffect(() => {
    const fromUrl = chatFromUrl();
    if (fromUrl) {
      setChat(fromUrl);
      setTab(fromUrl.kind);
      setEditing(new URLSearchParams(window.location.search).get("edit") === "1");
      setDetail(tabFromUrl());
      return;
    }
    try {
      const saved = window.localStorage.getItem(TAB_KEY);
      if (saved === "agent" || saved === "workflow") setTab(saved);
    } catch {
      /* default */
    }
  }, []);
  const pickTab = (t: BuildMode) => {
    setTab(t);
    setError(null);
    try {
      window.localStorage.setItem(TAB_KEY, t);
    } catch {
      /* ignore */
    }
  };
  const openChat = (target: ChatTarget | null, view: DetailTab = "overview") => {
    setChat(target);
    setEditing(false);
    setDetail(view);
    setChatUrl(target, false, view);
  };
  const pickDetail = (view: DetailTab) => {
    setDetail(view);
    setChatUrl(chat, editing, view);
  };
  /** Open an agent/workflow on the canvas (left) with its details (right). */
  const openEditor = (target: BuildTarget) => {
    setChat(target);
    setTab(target.kind);
    setEditing(true);
    setChatUrl(target, true, detail);
  };
  const closeEditor = () => {
    setEditing(false);
    setChatUrl(chat, false, detail);
  };

  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });
  const overview = useQuery({ queryKey: ["builder-overview", WINDOW], queryFn: () => builderApi.overview(token, WINDOW), enabled: !!token, refetchInterval: 15000 });
  const catalog = useQuery({ queryKey: ["catalog", token, ""], queryFn: () => vendorApi.getCatalog(token), enabled: !!token });

  const stats = useMemo(() => new Map((overview.data?.items ?? []).map((i) => [`${i.kind}:${i.id}`, i])), [overview.data]);
  const serverNames = useMemo(() => new Map((catalog.data?.servers ?? []).map((s) => [s.id, { name: s.name, connected: !!s.connected }])), [catalog.data]);

  const all: Item[] = useMemo(
    () =>
      tab === "agent"
        ? (agents.data ?? []).map((a) => ({
            kind: "agent" as const, id: a.id, name: a.name, sub: a.goal, updated: a.updated_at, canManage: a.can_manage, mine: a.owner_id === userId,
            servers: [...new Set((a.config.tool_ids ?? []).map(serverIdOf).filter(Boolean) as string[])],
            stats: stats.get(`agent:${a.id}`),
          }))
        : (workflows.data ?? []).map((w) => ({
            kind: "workflow" as const, id: w.id, name: w.name, sub: w.description || `${w.node_count} steps`, updated: w.updated_at, canManage: w.can_manage, mine: w.owner_id === userId,
            servers: [], stats: stats.get(`workflow:${w.id}`),
          })),
    [tab, agents.data, workflows.data, stats, userId],
  );

  const matches = (i: Item, f: Filter) => {
    const s = i.stats;
    switch (f) {
      case "attention": return !!s && (s.health_status === "needs_attention" || s.waiting > 0 || s.last_status === "failed");
      case "live": return !!s && s.running + s.waiting > 0;
      case "never": return !s?.last_run_at;
      case "scheduled": return !!s?.schedule;
      case "published": return (s?.published ?? 0) > 0;
      case "mine": return i.mine;
      case "shared": return !i.mine;
      default: return true;
    }
  };
  const needle = query.trim().toLowerCase();
  const items = all
    .filter((i) => matches(i, filter) && (!needle || i.name.toLowerCase().includes(needle) || i.sub.toLowerCase().includes(needle)))
    .sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "runs") return (b.stats?.runs ?? 0) - (a.stats?.runs ?? 0) || a.name.localeCompare(b.name);
      if (sort === "health") {
        const ha = a.stats ? HEALTH[a.stats.health_status].order : 9;
        const hb = b.stats ? HEALTH[b.stats.health_status].order : 9;
        return ha - hb || (a.stats?.health_score ?? 0) - (b.stats?.health_score ?? 0);
      }
      return (b.stats?.last_run_at ?? b.updated).localeCompare(a.stats?.last_run_at ?? a.updated);
    });
  const loading = tab === "agent" ? agents.isLoading : workflows.isLoading;
  const counts = Object.fromEntries((Object.keys(FILTERS) as Filter[]).map((f) => [f, all.filter((i) => matches(i, f)).length])) as Record<Filter, number>;

  const list = (
    <div className={cn("@container flex min-h-0 flex-col rounded-xl border border-zinc-200 bg-white", chat && "flex-1")}>
      <div className="flex flex-wrap items-center gap-1 border-b border-zinc-100 px-3 py-2" role="tablist" aria-label="Project items">
        {(["agent", "workflow"] as BuildMode[]).map((t) => {
          const count = t === "agent" ? agents.data?.length : workflows.data?.length;
          return (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => pickTab(t)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium cursor-pointer",
                tab === t ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900",
              )}
            >
              {t === "agent" ? <Bot className="h-4 w-4" /> : <Network className="h-4 w-4" />}
              {t === "agent" ? "Agents" : "Workflows"}
              {count != null && <span className={cn("text-xs", tab === t ? "text-zinc-300" : "text-zinc-400")}>{count}</span>}
            </button>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              aria-label="Search"
              className="h-8 w-28 rounded-md border border-zinc-200 bg-white pl-7 pr-2 text-xs text-zinc-900 placeholder:text-zinc-400 focus:w-40 focus:border-indigo-400 focus:outline-none transition-[width]"
            />
          </div>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort by" className="h-8 rounded-md border border-zinc-200 bg-white px-1.5 text-xs text-zinc-700">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
      <div className="flex gap-1.5 overflow-x-auto border-b border-zinc-100 px-3 py-2" role="tablist" aria-label="Filter">
        {/* Only the ones that would narrow it down ("Mine" when they're all yours wouldn't). */}
        {(Object.keys(FILTERS) as Filter[]).filter((f) => f === "all" || (counts[f] > 0 && counts[f] < counts.all) || filter === f).map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={filter === f}
            onClick={() => setFilter(f)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium cursor-pointer",
              filter === f ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "border-zinc-200 text-zinc-600 hover:text-zinc-900",
            )}
          >
            {FILTERS[f]} <span className="tabular-nums text-zinc-500">{counts[f]}</span>
          </button>
        ))}
      </div>
      {loading ? (
        <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>
      ) : all.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-zinc-500">Nothing here yet. Start one with New {tab}.</p>
      ) : items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-zinc-500">
          None match. <button type="button" className="font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer" onClick={() => { setFilter("all"); setQuery(""); }}>Show all</button>
        </p>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-zinc-100 overflow-y-auto">
          {items.map((item) => (
            <Row
              key={item.id}
              item={item}
              active={chat?.kind === item.kind && chat.id === item.id}
              chatActive={detail === "chat"}
              serverNames={serverNames}
              onOpen={(view) => openChat({ kind: item.kind, id: item.id }, view)}
              onEdit={() => openEditor({ kind: item.kind, id: item.id })}
              onDelete={() => {
                if (window.confirm(`Delete "${item.name}"? This can't be undone.`)) {
                  remove.mutate({ kind: item.kind, id: item.id });
                  if (chat?.id === item.id) openChat(null);
                }
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );

  const actions = (
    <Button variant="outline" disabled={createBlank.isPending} onClick={() => createBlank.mutate(tab)} aria-label={`New blank ${tab}`}>
      {createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} <span className="hidden xl:inline">New blank {tab}</span>
    </Button>
  );

  // A saved wizard hands its agent over: open it on the canvas here.
  const wizard = <AgentWizardHost onOpen={openEditor} />;

  // The list, full width; once one is picked it keeps the left third and its
  // details take the rest. Editing swaps the list for the canvas. A phone
  // shows one side at a time.
  return (
    <ProtectedDashboard path="/user" title="Executions" description="Every agent and workflow: what it does, how it's set up, how it's doing, and a chat with it." fullBleed>
      <div className="flex h-dvh overflow-hidden bg-zinc-950">
        {editing && chat ? (
          <section className="flex min-w-0 flex-1 flex-col [&>div]:h-full" aria-label="Editor">
            {chat.kind === "workflow" ? (
              <WorkflowEditor key={chat.id} id={chat.id} onBack={closeEditor} onOpen={openEditor} onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })} />
            ) : (
              <AgentEditor key={chat.id} id={chat.id} onBack={closeEditor} onOpen={openEditor} />
            )}
          </section>
        ) : (
          <section className={cn("min-w-0 flex-col gap-3 p-4 lg:p-6", chat ? "hidden md:flex md:w-2/5 lg:w-1/3" : "mx-auto flex w-full max-w-6xl flex-1")}>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0">
                <h1 className="text-lg font-bold text-zinc-900">Executions</h1>
                {!chat && <p className="text-xs text-zinc-500">Every agent and workflow, how it&apos;s doing, and a chat with it.</p>}
              </div>
              <div className="ml-auto">{actions}</div>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            {list}
          </section>
        )}
        {chat && !editing && (
          <section className="flex min-w-0 flex-1 flex-col border-zinc-200 shadow-xl md:border-l" aria-label="Details">
            <ProjectDetail
              key={`${chat.kind}:${chat.id}`}
              target={chat}
              token={token}
              tab={detail}
              onTab={pickDetail}
              onClose={() => openChat(null)}
              onOpenCanvas={() => openEditor(chat)}
            />
          </section>
        )}
      </div>
      {wizard}
    </ProtectedDashboard>
  );
}

/** Runs per day as tiny bars: the shape of its week, at a glance. */
function Spark({ daily }: { daily: number[] }) {
  const max = Math.max(1, ...daily);
  const total = daily.reduce((a, b) => a + b, 0);
  return (
    <span className="flex h-5 items-end gap-[2px]" role="img" aria-label={`${total} runs in the last ${daily.length} days`} title={daily.map((n, i) => `${daily.length - 1 - i === 0 ? "today" : `${daily.length - 1 - i}d ago`}: ${n}`).reverse().join("\n")}>
      {daily.map((n, i) => (
        <span key={i} className={cn("w-1 rounded-t-[2px]", n ? (i === daily.length - 1 ? "bg-indigo-500" : "bg-indigo-400/60") : "bg-zinc-200")} style={{ height: n ? `${Math.max(20, (n / max) * 100)}%` : "2px" }} />
      ))}
    </span>
  );
}

function Row({
  item,
  active,
  chatActive,
  serverNames,
  onOpen,
  onEdit,
  onDelete,
}: {
  item: Item;
  active: boolean;
  chatActive: boolean;
  serverNames: Map<string, { name: string; connected: boolean }>;
  onOpen: (view: DetailTab) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const s = item.stats;
  const h = s ? HEALTH[s.health_status] : null;
  const finished = s ? s.succeeded + s.failed : 0;
  const servers = item.servers.map((id) => serverNames.get(id)).filter(Boolean) as { name: string; connected: boolean }[];
  const failedLast = s?.last_status === "failed";

  // One quiet line under the name; anything that needs you comes first, in colour.
  const meta: React.ReactNode[] = [];
  if (s?.waiting) meta.push(<span key="w" className="inline-flex items-center gap-1 font-medium text-amber-700"><ShieldAlert className="h-3 w-3" /> waiting for you</span>);
  if (s?.running) meta.push(<span key="r" className="inline-flex items-center gap-1 text-sky-700"><Loader2 className="h-3 w-3 animate-spin" /> running</span>);
  meta.push(
    s?.last_run_at ? (
      <span key="l" className={cn(failedLast && "text-red-600")}>{failedLast ? "failed" : "ran"} {ago(s.last_run_at)}</span>
    ) : (
      <span key="l">never run</span>
    ),
  );
  if (s?.runs) meta.push(<span key="n" className="tabular-nums">{s.runs} run{s.runs === 1 ? "" : "s"}{finished ? ` · ${Math.round((s.succeeded / finished) * 100)}% ok` : ""}</span>);
  if (s?.schedule) meta.push(<span key="s" className="inline-flex items-center gap-1" title={s.next_run_at ? `Next: ${new Date(s.next_run_at).toLocaleString()}` : s.schedule}><CalendarClock className="h-3 w-3" /> {cronLabel(s.schedule)}</span>);
  if (s?.published) meta.push(<span key="p" className="inline-flex items-center gap-1" title="Published with a public key"><Globe className="h-3 w-3" /> live</span>);
  if (!item.mine) meta.push(<span key="m" className="inline-flex items-center gap-1" title="Shared by a teammate"><Users className="h-3 w-3" /> shared</span>);

  return (
    <li className={cn("group relative", active ? "bg-indigo-50/70" : "hover:bg-zinc-50")}>
      {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-r bg-indigo-500" aria-hidden />}
      <button
        type="button"
        onClick={() => onOpen("overview")}
        aria-current={active ? "true" : undefined}
        title={item.sub}
        className="flex w-full items-center gap-3 py-3 pl-4 pr-3 text-left cursor-pointer"
      >
        <span className="relative shrink-0">
          <Avatar name={item.name} size={36} />
          {h && <span className={cn("absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white", s?.running ? "animate-pulse bg-sky-500" : h.dot)} title={s?.running ? "Running now" : h.label} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate text-sm font-medium", active ? "text-indigo-700" : "text-zinc-900")}>{item.name}</span>
          <span className="hidden truncate text-xs text-zinc-500 @xl:block">{item.sub}</span>
          <span className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-zinc-500">
            {meta.map((m, i) => (
              <span key={i} className="inline-flex items-center gap-1.5">
                {i > 0 && <span className="text-zinc-300" aria-hidden>·</span>}
                {m}
              </span>
            ))}
          </span>
        </span>
        {servers.length > 0 && (
          <span className="hidden shrink-0 items-center -space-x-1 @lg:flex">
            {servers.slice(0, 3).map((srv) => (
              <span key={srv.name} title={`${srv.name}${srv.connected ? "" : ": not connected"}`} className={cn("rounded-md", !srv.connected && "ring-1 ring-red-400")}>
                <ConnectorIcon name={srv.name} size="xs" />
              </span>
            ))}
          </span>
        )}
        {s && s.runs > 0 && <span className="hidden shrink-0 @lg:block"><Spark daily={s.daily} /></span>}
        {/* The score, until the pointer brings the actions. */}
        {h && s?.health_score != null && (
          <span
            className={cn(
              "w-9 shrink-0 rounded-md py-0.5 text-center text-xs font-semibold tabular-nums transition-opacity group-hover:opacity-0 group-focus-within:opacity-0",
              s.health_status === "production_ready" ? "bg-emerald-50 text-emerald-700" : s.health_status === "not_tested" ? "bg-zinc-100 text-zinc-500" : "bg-amber-50 text-amber-700",
            )}
            title={`Health: ${h.label}, ${s.health_score}/100`}
          >
            {s.health_score}
          </span>
        )}
      </button>
      <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center rounded-lg bg-white opacity-0 shadow-sm transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <button type="button" onClick={() => onOpen("chat")} aria-label={`Chat with ${item.name}`} title="Chat" className={cn("rounded-md p-1.5 hover:bg-indigo-50 hover:text-indigo-600 cursor-pointer", active && chatActive ? "text-indigo-500" : "text-zinc-500")}>
          <MessageSquare className="h-4 w-4" />
        </button>
        <button type="button" onClick={onEdit} aria-label={`Edit ${item.name}`} title="Open on the canvas" className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 cursor-pointer">
          <Pencil className="h-4 w-4" />
        </button>
        {item.canManage && (
          <button type="button" aria-label={`Delete ${item.name}`} title="Delete" className="rounded-md p-1.5 text-zinc-500 hover:bg-red-50 hover:text-red-600 cursor-pointer" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </span>
    </li>
  );
}
