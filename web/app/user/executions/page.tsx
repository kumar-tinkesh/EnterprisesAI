"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, CalendarClock, CheckCircle2, ChevronDown, Clock, Eye, Globe, Loader2, MessageSquare, PanelLeftClose, PanelLeftOpen, Plus, RefreshCw, Search, ShieldAlert, Users, X, XCircle } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { Tabs } from "@/components/ui/tabs";
import { Select } from "@/components/builder/fields";
import { type ChatTarget } from "@/components/builder/chat/chat-panel";
import { ProjectDetail, type DetailTab } from "@/components/builder/project-detail";
import { AgentEditor } from "@/components/builder/agent-editor";
import { WorkflowEditor } from "@/components/builder/workflow-editor";
import { AgentWizardHost } from "@/components/builder/agent-wizard/agent-wizard";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { TypeIcon } from "@/components/builder/type-icon";
import { vendorApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { serverIdOf } from "@/lib/builder/graph";
import type { OverviewItem, Run, RunStatus } from "@/lib/builder/types";
import { useBuilderActions, type BuildMode, type BuildTarget } from "@/lib/builder/use-builder-actions";
import { Templates } from "@/app/user/agents/agent-canvas";
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
  needs_attention: { label: "Needs attention", dot: "bg-amber-400/90", text: "text-zinc-300", order: 0 },
  testing: { label: "In testing", dot: "bg-sky-400/80", text: "text-zinc-400", order: 1 },
  not_tested: { label: "Not tested", dot: "bg-zinc-500", text: "text-zinc-500", order: 2 },
  production_ready: { label: "Ready", dot: "bg-[var(--success)]", text: "text-emerald-400", order: 3 },
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

/** Always shown (when they'd narrow it down); the rest sit under More. */
const MAIN_FILTERS: Filter[] = ["all", "attention", "live", "scheduled"];
const MORE_FILTERS: Filter[] = ["never", "published", "mine", "shared"];

const SORTS = { last_run: "Last run", runs: "Most runs", success: "Success rate", health: "Status", name: "Name" } as const;
type Sort = keyof typeof SORTS;

/** The columns on a wide list; a narrow one folds them into a line under the name. */
const GRID = "@3xl:grid @3xl:grid-cols-[minmax(0,1fr)_9.5rem_7rem_5rem_5rem_7rem] @3xl:gap-4";

const successOf = (s: OverviewItem | undefined) => (s && s.succeeded + s.failed ? s.succeeded / (s.succeeded + s.failed) : null);

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
  const router = useRouter();
  const token = useAuthStore((s) => s.accessToken) || "";
  const userId = useAuthStore((s) => s.user?.id);
  const [viewMode, setViewMode] = useState<"runs" | "inspector">(() => {
    if (typeof window !== "undefined") {
      const p = new URLSearchParams(window.location.search);
      if (p.has("chat")) return "inspector";
      if (p.get("view") === "inspector") return "inspector";
    }
    return "runs";
  });
  const [tab, setTab] = useState<BuildMode>("agent");
  const [chat, setChat] = useState<ChatTarget | null>(null);
  // The selected one is open on the canvas, in place of the list.
  const [editing, setEditing] = useState(false);
  const [detail, setDetail] = useState<DetailTab>("overview");
  const [listCollapsed, setListCollapsed] = useState(false);
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
      setViewMode("inspector");
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
    if (target) setViewMode("inspector");
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
  /** The editor's Chat button: back from the canvas, onto its Chat tab. */
  const openChatTab = () => {
    setEditing(false);
    setDetail("chat");
    setChatUrl(chat, false, "chat");
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
      // What needs you now: a fresh decision, or a recent failure (an old one, or one left waiting for weeks, doesn't).
      case "attention": return !!s && (s.health_status === "needs_attention" || s.waiting > 0 || (s.last_status === "failed" && recent(s.last_run_at)));
      case "live": return !!s && s.running > 0;
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
      if (sort === "success") return (successOf(b.stats) ?? -1) - (successOf(a.stats) ?? -1) || a.name.localeCompare(b.name);
      if (sort === "health") {
        const ha = a.stats ? HEALTH[a.stats.health_status].order : 9;
        const hb = b.stats ? HEALTH[b.stats.health_status].order : 9;
        return ha - hb || (a.stats?.health_score ?? 0) - (b.stats?.health_score ?? 0);
      }
      return (b.stats?.last_run_at ?? b.updated).localeCompare(a.stats?.last_run_at ?? a.updated);
    });
  const loading = tab === "agent" ? agents.isLoading : workflows.isLoading;
  const counts = Object.fromEntries((Object.keys(FILTERS) as Filter[]).map((f) => [f, all.filter((i) => matches(i, f)).length])) as Record<Filter, number>;

  const narrows = (f: Filter) => f === "all" || filter === f || (counts[f] > 0 && counts[f] < counts.all);
  const moreShown = MORE_FILTERS.filter(narrows);
  // What needs you goes first, in its own group, unless a filter already picked what to show.
  const attention = filter === "all" ? items.filter((i) => matches(i, "attention")) : [];
  const groups =
    attention.length && attention.length < items.length
      ? [
          { label: "Needs your attention", items: attention },
          { label: "Everything else", items: items.filter((i) => !attention.includes(i)) },
        ]
      : [{ label: null, items }];
  const renderRow = (item: Item) => (
    <Row
      key={item.id}
      item={item}
      active={chat?.kind === item.kind && chat.id === item.id}
      serverNames={serverNames}
      onOpen={(view) => {
        if (view === "chat") {
          router.push(`/user/agents?workspace=${item.kind}:${encodeURIComponent(item.id)}&tab=chat`);
        } else {
          openChat({ kind: item.kind, id: item.id }, view);
        }
      }}
      onEdit={() => openEditor({ kind: item.kind, id: item.id })}
      onDelete={() => {
        if (window.confirm(`Delete "${item.name}"? This can't be undone.`)) {
          remove.mutate({ kind: item.kind, id: item.id });
          if (chat?.id === item.id) openChat(null);
        }
      }}
    />
  );

  const list = (
    <div className={cn("@container flex min-h-0 flex-col gap-3", chat && "flex-1")}>
      <Tabs
        value={tab}
        onChange={pickTab}
        tabs={(["agent", "workflow"] as BuildMode[]).map((t) => {
          const count = t === "agent" ? agents.data?.length : workflows.data?.length;
          return [t, `${t === "agent" ? "Agents" : "Workflows"}${count != null ? ` · ${count}` : ""}`] as const;
        })}
      />
      <div className="flex gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
          <Input className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Search ${tab}s`} aria-label="Search" />
        </div>
        {/* A wide list sorts by its column headings instead. */}
        <Select className="w-auto shrink-0 @3xl:hidden" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort by">
          {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </div>
      {all.length > 0 && (
        <div className="no-scrollbar -mx-4 flex items-center gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0" role="tablist" aria-label="Filter">
          {MAIN_FILTERS.filter(narrows).map((f) => (
            <FilterTab key={f} on={filter === f} onClick={() => setFilter(f)}>
              {FILTERS[f]} <span className="tabular-nums text-zinc-500">{counts[f]}</span>
            </FilterTab>
          ))}
          {moreShown.length > 0 && (
            <Menu
              label="More filters"
              trigger={
                <>
                  {MORE_FILTERS.includes(filter) ? FILTERS[filter] : "More"} <ChevronDown className="h-3.5 w-3.5" />
                </>
              }
              triggerClassName={cn(
                "inline-flex shrink-0 items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer",
                MORE_FILTERS.includes(filter) ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900",
              )}
              items={moreShown.map((f) => ({ label: `${FILTERS[f]} (${counts[f]})`, checked: filter === f, onClick: () => setFilter(filter === f ? "all" : f) }))}
            />
          )}
        </div>
      )}
      {loading ? (
        <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>
      ) : all.length === 0 ? (
        // Nothing yet: ready-made workflows right here, one click from a working one.
        <div className="space-y-6">
          <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-8 text-center text-sm text-zinc-500">
            No {tab}s yet. Describe one with New {tab}{tab === "workflow" ? ", or start from one below" : ", or start from a ready-made workflow below"}.
          </p>
          <Templates onOpen={openEditor} title="Ready-made workflows" />
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-10 text-center text-sm text-zinc-500">
          None match. <button type="button" className="font-medium text-zinc-900 underline-offset-2 hover:underline cursor-pointer" onClick={() => { setFilter("all"); setQuery(""); }}>Show all</button>
        </p>
      ) : (
        <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-zinc-200">
          <div className={cn("hidden shrink-0 border-b border-zinc-200 px-4 py-2 text-xs font-medium text-zinc-500", GRID)} role="row">
            <SortHead id="name" sort={sort} onSort={setSort}>Name</SortHead>
            <SortHead id="health" sort={sort} onSort={setSort}>Status</SortHead>
            <SortHead id="last_run" sort={sort} onSort={setSort}>Last run</SortHead>
            <SortHead id="runs" sort={sort} onSort={setSort} right>Runs ({WINDOW}d)</SortHead>
            <SortHead id="success" sort={sort} onSort={setSort} right>Success</SortHead>
            <span />
          </div>
          <div className="min-h-0 overflow-y-auto">
            {groups.map((g) => (
              <section key={g.label ?? "all"} aria-label={g.label ?? undefined}>
                {g.label && (
                  <h2 className={cn("border-b border-zinc-100 bg-zinc-50 px-4 py-1.5 text-xs font-medium flex items-center gap-1.5", g.items === attention ? "text-zinc-300 font-medium" : "text-zinc-400")}>
                    {g.items === attention && <span className="h-1.5 w-1.5 rounded-full bg-amber-400/80 shrink-0" />}
                    <span>{g.label} · {g.items.length}</span>
                  </h2>
                )}
                <ul className="divide-y divide-zinc-100 border-b border-zinc-100 last:border-b-0">{g.items.map(renderRow)}</ul>
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  // A saved wizard hands its agent over: open it on the canvas here.
  const wizard = <AgentWizardHost onOpen={openEditor} />;

  // The list, full width; once one is picked it keeps the left third and its
  // details take the rest. Editing swaps the list for the canvas. A phone
  // shows one side at a time.
  return (
    <ProtectedDashboard path="/user" title="Executions & Logs" description="Live execution history across all agents, with deep run traces." fullBleed>
      <div className="flex h-full overflow-hidden bg-[var(--bg)]">
        {editing && chat ? (
          <section className="flex min-w-0 flex-1 flex-col [&>div]:h-full" aria-label="Editor">
            {chat.kind === "workflow" ? (
              <WorkflowEditor key={chat.id} id={chat.id} onBack={closeEditor} onChat={openChatTab} onOpen={openEditor} onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })} />
            ) : (
              <AgentEditor key={chat.id} id={chat.id} onBack={closeEditor} onChat={openChatTab} onOpen={openEditor} />
            )}
          </section>
        ) : viewMode === "runs" && !chat ? (
          <section className="animate-fade-up mx-auto flex h-full min-h-0 w-full max-w-6xl flex-1 flex-col gap-5 overflow-hidden px-4 py-6 sm:px-8 sm:py-8">
            <header className="flex shrink-0 flex-wrap items-end justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-xl font-semibold text-zinc-900">Executions & Logs</h1>
                  <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      aria-selected="true"
                      onClick={() => setViewMode("runs")}
                      className="rounded-md bg-white/[0.1] px-3 py-1 text-xs font-medium text-white shadow-xs cursor-pointer transition-colors"
                    >
                      Run Logs
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected="false"
                      onClick={() => setViewMode("inspector")}
                      className="rounded-md px-3 py-1 text-xs font-medium text-zinc-400 hover:text-white hover:bg-white/[0.04] cursor-pointer transition-colors"
                    >
                      Agent Inspector
                    </button>
                  </div>
                </div>
                <p className="mt-1 text-sm text-zinc-500">Live execution history across all agents, with deep run traces.</p>
              </div>
            </header>
            <RunLogsView
              token={token}
              onOpenChat={(target) => {
                router.push(`/user/agents?workspace=${target.kind}:${encodeURIComponent(target.id)}&tab=chat`);
              }}
            />
          </section>
        ) : (
          <section
            className={cn(
              "animate-fade-up min-h-0 min-w-0 flex-col gap-5 overflow-hidden px-4 py-6 sm:px-8 sm:py-8 transition-all duration-200",
              chat
                ? listCollapsed
                  ? "hidden"
                  : "hidden md:flex md:w-2/5 md:px-4 lg:w-1/3 lg:px-6"
                : "mx-auto flex w-full max-w-6xl flex-1"
            )}
          >
            <header className="flex flex-wrap items-end justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-xl font-semibold text-zinc-900">Executions & Logs</h1>
                  {!chat && (
                    <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5" role="tablist">
                      <button
                        type="button"
                        role="tab"
                        aria-selected="false"
                        onClick={() => setViewMode("runs")}
                        className="rounded-md px-3 py-1 text-xs font-medium text-zinc-400 hover:text-white hover:bg-white/[0.04] cursor-pointer transition-colors"
                      >
                        Run Logs
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected="true"
                        onClick={() => setViewMode("inspector")}
                        className="rounded-md bg-white/[0.1] px-3 py-1 text-xs font-medium text-white shadow-xs cursor-pointer transition-colors"
                      >
                        Agent Inspector
                      </button>
                    </div>
                  )}
                </div>
                {!chat && <p className="mt-1 text-sm text-zinc-500">Every agent and workflow, how it&apos;s doing, and a chat with it.</p>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button className="shrink-0" disabled={createBlank.isPending} onClick={() => createBlank.mutate(tab)}>
                  {createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} New {tab}
                </Button>
                {chat && (
                  <button
                    type="button"
                    onClick={() => setListCollapsed(true)}
                    title="Collapse agents list"
                    aria-label="Collapse agents list"
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] text-zinc-400 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors"
                  >
                    <PanelLeftClose className="h-4 w-4" />
                  </button>
                )}
              </div>
            </header>
            {error && <p className="text-sm text-red-600">{error}</p>}
            {list}
          </section>
        )}
        {chat && !editing && (
          <section className="flex min-w-0 flex-1 flex-col border-zinc-200 md:border-l" aria-label="Details">
            <ProjectDetail
              key={`${chat.kind}:${chat.id}`}
              target={chat}
              token={token}
              tab={detail}
              onTab={pickDetail}
              onClose={() => openChat(null)}
              onOpenCanvas={() => openEditor(chat)}
              onSwitchTarget={(newTarget) => openChat(newTarget, detail)}
              isListCollapsed={listCollapsed}
              onToggleList={() => setListCollapsed(false)}
            />
          </section>
        )}
      </div>
      {wizard}
    </ProtectedDashboard>
  );
}

function FilterTab({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer",
        on ? "bg-white/[0.1] text-white" : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200",
      )}
    >
      {children}
    </button>
  );
}

/** A column heading that sorts the list by itself. */
function SortHead({ id, sort, onSort, right, children }: { id: Sort; sort: Sort; onSort: (s: Sort) => void; right?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => onSort(id)}
      aria-pressed={sort === id}
      className={cn("inline-flex items-center gap-1 hover:text-zinc-900 cursor-pointer", right && "justify-self-end", sort === id && "text-zinc-900")}
    >
      {children}
      {sort === id && <ArrowDown className="h-3 w-3" />}
    </button>
  );
}

/** Within the last week: what "needs your attention" looks back over. */
function recent(iso: string | null): boolean {
  return !!iso && Date.now() - new Date(iso).getTime() < 7 * 86400000;
}

/** Running, waiting for you, or how ready it is: a dot and a word. */
function StatusLabel({ s, className }: { s: OverviewItem | undefined; className?: string }) {
  const cls = cn("items-center gap-1.5 text-sm", className);
  if (s?.running) return <span className={cn(cls, "text-zinc-300")}><Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" /> Running</span>;
  if (s?.waiting) return <span className={cn(cls, "font-medium text-zinc-300")}><ShieldAlert className="h-3.5 w-3.5 text-amber-400/80" /> Waiting for you</span>;
  const h = HEALTH[s?.health_status ?? "not_tested"];
  return (
    <span className={cn(cls, h.text)}>
      <span className={cn("h-2 w-2 shrink-0 rounded-full", h.dot)} aria-hidden /> {h.label}
    </span>
  );
}

function Row({
  item,
  active,
  serverNames,
  onOpen,
  onEdit,
  onDelete,
}: {
  item: Item;
  active: boolean;
  serverNames: Map<string, { name: string; connected: boolean }>;
  onOpen: (view: DetailTab) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const s = item.stats;
  const rate = successOf(s);
  const servers = item.servers.map((id) => serverNames.get(id)).filter(Boolean) as { name: string; connected: boolean }[];
  const lastRun = s?.last_run_at ? (
    <span className={cn(s.last_status === "failed" && "text-red-600")}>{s.last_status === "failed" ? "Failed " : ""}{ago(s.last_run_at)}</span>
  ) : (
    <span>Never</span>
  );

  // What the columns don't show: when it runs on its own, where it's live, who owns it, which apps it uses.
  const extras: React.ReactNode[] = [];
  if (s?.schedule) extras.push(<span key="s" className="inline-flex items-center gap-1" title={s.next_run_at ? `Next: ${new Date(s.next_run_at).toLocaleString()}` : s.schedule}><CalendarClock className="h-3 w-3" /> {cronLabel(s.schedule)}</span>);
  if (s?.stale_waiting) {
    extras.push(
      <span key="w" className="inline-flex items-center gap-1 text-zinc-400" title="Waiting for a decision for over a week. Decide in its chat, or cancel it from the Dashboard.">
        <ShieldAlert className="h-3 w-3 text-zinc-400" /> {s.stale_waiting} old approval{s.stale_waiting === 1 ? "" : "s"}
      </span>,
    );
  }
  if (s?.published) extras.push(<span key="p" className="inline-flex items-center gap-1 text-zinc-400"><Globe className="h-3 w-3" /> Published</span>);
  if (!item.mine) extras.push(<span key="m" className="inline-flex items-center gap-1 text-zinc-400" title="Shared by a teammate"><Users className="h-3 w-3" /> Shared</span>);
  if (servers.length) {
    extras.push(
      <span key="c" className="inline-flex items-center -space-x-1">
        {servers.slice(0, 4).map((srv) => (
          <span key={srv.name} title={`${srv.name}${srv.connected ? "" : ": not connected"}`} className={cn("rounded-md", !srv.connected && "ring-1 ring-red-400")}>
            <ConnectorIcon name={srv.name} size="xs" />
          </span>
        ))}
      </span>,
    );
  }

  return (
    <li
      onClick={() => onOpen("overview")}
      className={cn(
        "group flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors @3xl:items-center",
        GRID,
        active ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"
      )}
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <TypeIcon kind={item.kind} />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpen("overview");
            }}
            aria-current={active ? "true" : undefined}
            className="block max-w-full truncate text-left text-sm font-medium text-zinc-100 group-hover:text-white cursor-pointer"
          >
            {item.name}
          </button>
          {/* Narrow: the columns, folded into one line. */}
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-400 @3xl:hidden">
            <StatusLabel s={s} className="inline-flex text-xs" />
            {lastRun}
            {s?.runs ? <span className="tabular-nums">{s.runs} runs{rate !== null ? `, ${Math.round(rate * 100)}%` : ""}</span> : null}
          </p>
          {extras.length > 0 && <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-400">{extras}</p>}
        </div>
      </div>
      <StatusLabel s={s} className="hidden @3xl:flex" />
      <span className="hidden text-sm text-zinc-400 group-hover:text-zinc-200 @3xl:block">{lastRun}</span>
      <span className="hidden text-right text-sm tabular-nums text-zinc-400 group-hover:text-zinc-200 @3xl:block">{s?.runs || "—"}</span>
      <span className="hidden text-right text-sm tabular-nums text-zinc-400 group-hover:text-zinc-200 @3xl:block">{rate !== null ? `${Math.round(rate * 100)}%` : "—"}</span>
      <div className="flex shrink-0 items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        <Button size="sm" variant="outline" onClick={() => onOpen("chat")} aria-label={`Chat with ${item.name}`}>
          <MessageSquare /> <span className="hidden @md:inline">Chat</span>
        </Button>
        <Menu
          label={`More for ${item.name}`}
          items={[
            { label: "Open on canvas", onClick: onEdit },
            ...(item.canManage ? [{ label: "Delete", danger: true, onClick: onDelete }] : []),
          ]}
        />
      </div>
    </li>
  );
}

const RUN_STATUS: Record<RunStatus, { label: string; Icon: typeof CheckCircle2; className: string; pill: string }> = {
  succeeded: { label: "Succeeded", Icon: CheckCircle2, className: "text-emerald-400", pill: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" },
  failed: { label: "Failed", Icon: XCircle, className: "text-red-400", pill: "bg-red-500/10 text-red-400 border border-red-500/20" },
  running: { label: "Running", Icon: Loader2, className: "text-indigo-400 animate-spin", pill: "bg-indigo-500/10 text-indigo-300 border border-indigo-500/20" },
  queued: { label: "Queued", Icon: Clock, className: "text-zinc-400", pill: "bg-white/[0.05] text-zinc-400 border border-white/10" },
  waiting: { label: "Waiting", Icon: ShieldAlert, className: "text-amber-400", pill: "bg-amber-500/10 text-amber-300 border border-amber-500/20" },
  cancelled: { label: "Cancelled", Icon: XCircle, className: "text-zinc-400", pill: "bg-white/[0.05] text-zinc-400 border border-white/10" },
};

function runDuration(r: Run): string {
  if (!r.started_at || !r.finished_at) return "—";
  const diff = new Date(r.finished_at).getTime() - new Date(r.started_at).getTime();
  if (diff >= 60000) return `${Math.round(diff / 60000)}m`;
  if (diff >= 1000) return `${(diff / 1000).toFixed(1)}s`;
  return `${diff}ms`;
}

function runInputText(r: Run): string {
  if (r.input?.text?.trim()) return r.input.text;
  if (r.input?.attachments?.[0]?.filename) return `📎 ${r.input.attachments[0].filename}`;
  return r.kind === "workflow" ? "Workflow execution" : "—";
}

function RunLogsView({
  token,
  onOpenChat,
}: {
  token: string;
  onOpenChat: (target: ChatTarget) => void;
}) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [inspectRun, setInspectRun] = useState<Run | null>(null);

  const runsQuery = useQuery({
    queryKey: ["all-executions-runs"],
    queryFn: () => builderApi.listRuns(token, { limit: 100 }),
    enabled: !!token,
    refetchInterval: 10000,
  });

  const runs = runsQuery.data ?? [];
  const needle = query.trim().toLowerCase();
  const filtered = runs.filter((r) => {
    if (filter !== "all" && r.status !== filter) return false;
    if (!needle) return true;
    return (
      (r.name && r.name.toLowerCase().includes(needle)) ||
      (r.input?.text && r.input.text.toLowerCase().includes(needle)) ||
      (r.error && r.error.toLowerCase().includes(needle)) ||
      r.id.toLowerCase().includes(needle)
    );
  });

  const cancelRun = async (id: string) => {
    try {
      await builderApi.cancelRun(token, id);
      void queryClient.invalidateQueries({ queryKey: ["all-executions-runs"] });
    } catch {
      /* ignore */
    }
  };

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: runs.length };
    for (const r of runs) counts[r.status] = (counts[r.status] ?? 0) + 1;
    return counts;
  }, [runs]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {/* Controls row */}
      <div className="flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative min-w-0 flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
          <Input
            className="pl-9 text-xs"
            placeholder="Search runs by prompt, target, or ID…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void runsQuery.refetch()}
            disabled={runsQuery.isRefetching}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-3 text-xs font-medium text-zinc-300 hover:bg-white/[0.06] hover:text-white cursor-pointer transition-colors"
            title="Refresh runs"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", runsQuery.isRefetching && "animate-spin")} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter Chips */}
      <div className="no-scrollbar -mx-4 flex shrink-0 items-center gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0" role="tablist">
        {(["all", "succeeded", "failed", "running", "waiting", "cancelled"] as const).map((st) => {
          const count = statusCounts[st] ?? 0;
          if (st !== "all" && count === 0) return null;
          return (
            <button
              key={st}
              type="button"
              role="tab"
              aria-selected={filter === st}
              onClick={() => setFilter(st)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer capitalize",
                filter === st ? "bg-white/[0.1] text-white shadow-xs" : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200"
              )}
            >
              <span>{st === "all" ? "All Runs" : st}</span>
              <span className="tabular-nums text-zinc-400">({count})</span>
            </button>
          );
        })}
      </div>

      {/* Table / Empty State */}
      {runsQuery.isLoading ? (
        <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-zinc-400" /></div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] px-4 py-12 text-center text-sm text-zinc-400">
          {runs.length === 0 ? "No execution runs recorded yet. Chat with an agent to start a run." : `No runs match filter "${filter}".`}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-white/10 bg-[var(--surface)] shadow-xs">
          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-auto">
            <table className="w-full table-fixed border-separate border-spacing-0 text-left text-xs">
              <thead className="sticky top-0 z-10 bg-[var(--surface-raised)] text-zinc-400 font-medium">
                <tr>
                  <th className="w-28 border-b border-white/10 px-3.5 py-2.5">Status</th>
                  <th className="w-40 sm:w-48 border-b border-white/10 px-3.5 py-2.5">Target</th>
                  <th className="border-b border-white/10 px-3.5 py-2.5">Input / Query</th>
                  <th className="hidden w-20 border-b border-white/10 px-3.5 py-2.5 sm:table-cell">Duration</th>
                  <th className="hidden w-20 border-b border-white/10 px-3.5 py-2.5 lg:table-cell">Cost</th>
                  <th className="hidden w-24 border-b border-white/10 px-3.5 py-2.5 md:table-cell">Triggered</th>
                  <th className="w-32 sm:w-36 border-b border-white/10 px-3.5 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const meta = RUN_STATUS[r.status] ?? RUN_STATUS.queued;
                  const targetId = r.kind === "workflow" ? r.workflow_id : r.agent_id;
                  const targetName = r.name || (r.kind === "workflow" ? "Workflow" : "Agent");
                  const isPending = r.status === "running" || r.status === "waiting";
                  return (
                    <tr key={r.id} className="group transition-colors hover:bg-white/[0.04]">
                      <td className="w-28 whitespace-nowrap border-b border-white/5 px-3.5 py-3 align-middle group-last:border-b-0">
                        <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium", meta.pill)}>
                          <meta.Icon className="h-3 w-3 shrink-0" />
                          <span>{meta.label}</span>
                        </span>
                      </td>
                      <td className="w-40 sm:w-48 border-b border-white/5 px-3.5 py-3 align-middle font-medium text-zinc-200 group-hover:text-white group-last:border-b-0">
                        <div className="flex items-center gap-2 min-w-0">
                          <TypeIcon kind={r.kind} />
                          <span className="truncate">{targetName}</span>
                        </div>
                      </td>
                      <td className="border-b border-white/5 px-3.5 py-3 align-middle text-zinc-400 group-hover:text-zinc-200 group-last:border-b-0">
                        <div className="truncate" title={r.input?.text || ""}>
                          {runInputText(r)}
                        </div>
                      </td>
                      <td className="hidden w-20 whitespace-nowrap border-b border-white/5 px-3.5 py-3 align-middle tabular-nums text-zinc-400 group-hover:text-zinc-200 group-last:border-b-0 sm:table-cell">
                        {runDuration(r)}
                      </td>
                      <td className="hidden w-20 whitespace-nowrap border-b border-white/5 px-3.5 py-3 align-middle tabular-nums text-zinc-400 group-hover:text-zinc-200 group-last:border-b-0 lg:table-cell">
                        {r.cost_usd != null ? `$${r.cost_usd.toFixed(4)}` : "—"}
                      </td>
                      <td className="hidden w-24 whitespace-nowrap border-b border-white/5 px-3.5 py-3 align-middle text-zinc-400 group-hover:text-zinc-200 group-last:border-b-0 md:table-cell">
                        {ago(r.created_at)}
                      </td>
                      <td className="w-32 sm:w-36 whitespace-nowrap border-b border-white/5 px-3.5 py-3 align-middle text-right group-last:border-b-0">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => setInspectRun(r)}
                            className="inline-flex h-7 items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors"
                            title="Inspect Run"
                          >
                            <Eye className="h-3 w-3" /> Inspect
                          </button>
                          {targetId && (
                            <button
                              type="button"
                              onClick={() => onOpenChat({ kind: r.kind, id: targetId })}
                              className="inline-flex h-7 items-center gap-1 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-2 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 hover:text-indigo-200 cursor-pointer transition-colors"
                              title="Open in Chat"
                            >
                              <MessageSquare className="h-3 w-3" /> Chat
                            </button>
                          )}
                          {isPending && (
                            <button
                              type="button"
                              onClick={() => cancelRun(r.id)}
                              className="inline-flex h-7 items-center rounded-md border border-red-500/30 bg-red-500/10 px-2 text-xs font-medium text-red-400 hover:bg-red-500/20 cursor-pointer transition-colors"
                              title="Cancel Run"
                            >
                              Cancel
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {inspectRun && (
        <InspectRunDialog run={inspectRun} onClose={() => setInspectRun(null)} />
      )}
    </div>
  );
}

function InspectRunDialog({ run, onClose }: { run: Run; onClose: () => void }) {
  const meta = RUN_STATUS[run.status] ?? RUN_STATUS.queued;
  const targetName = run.name || (run.kind === "workflow" ? "Workflow" : "Agent");
  return (
    <Dialog title={`Run Trace: ${targetName}`} onClose={onClose}>
      <div className="space-y-4 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-3">
          <div className="flex items-center gap-2">
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", meta.pill)}>
              <meta.Icon className="h-3 w-3" /> {meta.label}
            </span>
            <span className="font-mono text-zinc-400">ID: {run.id.slice(0, 8)}…</span>
          </div>
          <span className="text-zinc-400 tabular-nums">Duration: {runDuration(run)}</span>
        </div>

        {run.error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-red-300">
            <p className="font-semibold">Error Message:</p>
            <p className="mt-1 font-mono">{run.error}</p>
          </div>
        )}

        <div>
          <p className="font-semibold text-zinc-200">Input / Prompt:</p>
          <div className="mt-1 max-h-32 overflow-y-auto rounded-md border border-white/10 bg-white/[0.03] p-2.5 font-mono text-zinc-300">
            {run.input?.text || JSON.stringify(run.input, null, 2)}
          </div>
        </div>

        {(run.output_text || run.output?.text) && (
          <div>
            <p className="font-semibold text-zinc-200">Output Response:</p>
            <div className="mt-1 max-h-48 overflow-y-auto rounded-md border border-white/10 bg-white/[0.03] p-2.5 text-zinc-300 whitespace-pre-wrap">
              {run.output_text || run.output?.text}
            </div>
          </div>
        )}

        {run.tool_calls && run.tool_calls.length > 0 && (
          <div>
            <p className="font-semibold text-zinc-200">Tool Calls ({run.tool_calls.length}):</p>
            <ul className="mt-1 space-y-1.5">
              {run.tool_calls.map((tc, idx) => (
                <li key={idx} className="rounded-md border border-white/10 bg-white/[0.03] p-2 text-xs">
                  <div className="flex items-center justify-between font-mono font-medium text-zinc-200">
                    <span>{tc.tool_name}</span>
                    <span className="text-[11px] text-zinc-400">{tc.duration_ms ? `${tc.duration_ms}ms` : ""}</span>
                  </div>
                  {tc.result_preview && (
                    <p className="mt-1 truncate font-mono text-[11px] text-zinc-400">{tc.result_preview}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex items-center justify-between border-t border-white/10 pt-3 text-zinc-400">
          <span>Tokens: {((run.prompt_tokens ?? 0) + (run.completion_tokens ?? 0)).toLocaleString()}</span>
          <span>Cost: {run.cost_usd != null ? `$${run.cost_usd.toFixed(4)}` : "—"}</span>
        </div>
      </div>
    </Dialog>
  );
}
