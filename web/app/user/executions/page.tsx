"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, CalendarClock, ChevronDown, Globe, Loader2, MessageSquare, Plus, Search, ShieldAlert, Users } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
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
  needs_attention: { label: "Needs attention", dot: "bg-[var(--warning)]", text: "text-amber-700", order: 0 },
  testing: { label: "Testing", dot: "bg-[var(--warning)]", text: "text-amber-700", order: 1 },
  not_tested: { label: "Not tested", dot: "bg-zinc-400", text: "text-zinc-500", order: 2 },
  production_ready: { label: "Ready", dot: "bg-[var(--success)]", text: "text-emerald-700", order: 3 },
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
      onOpen={(view) => openChat({ kind: item.kind, id: item.id }, view)}
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
        <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-10 text-center text-sm text-zinc-500">No {tab}s yet. Create one with New {tab}.</p>
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
                  <h2 className={cn("border-b border-zinc-100 bg-zinc-50 px-4 py-1.5 text-xs font-medium", g.items === attention ? "text-amber-700" : "text-zinc-500")}>
                    {g.label} · {g.items.length}
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
    <ProtectedDashboard path="/user" title="Executions" description="Every agent and workflow, how it's doing, and a chat with it." fullBleed>
      <div className="flex h-full overflow-hidden bg-[var(--bg)]">
        {editing && chat ? (
          <section className="flex min-w-0 flex-1 flex-col [&>div]:h-full" aria-label="Editor">
            {chat.kind === "workflow" ? (
              <WorkflowEditor key={chat.id} id={chat.id} onBack={closeEditor} onOpen={openEditor} onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })} />
            ) : (
              <AgentEditor key={chat.id} id={chat.id} onBack={closeEditor} onOpen={openEditor} />
            )}
          </section>
        ) : (
          <section className={cn("min-w-0 flex-col gap-5 px-4 py-6 sm:px-8 sm:py-8", chat ? "hidden md:flex md:w-2/5 md:px-4 lg:w-1/3 lg:px-6" : "mx-auto flex w-full max-w-6xl flex-1")}>
            <header className="flex flex-wrap items-end justify-between gap-4">
              <div className="min-w-0">
                <h1 className="text-xl font-semibold text-zinc-900">Executions</h1>
                {!chat && <p className="mt-1 text-sm text-zinc-500">Every agent and workflow, how it&apos;s doing, and a chat with it.</p>}
              </div>
              <Button className="shrink-0" disabled={createBlank.isPending} onClick={() => createBlank.mutate(tab)}>
                {createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} New {tab}
              </Button>
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
        on ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900",
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

/** Running, waiting for you, or how ready it is: a dot and a word. */
function StatusLabel({ s, className }: { s: OverviewItem | undefined; className?: string }) {
  const cls = cn("items-center gap-1.5 text-sm", className);
  if (s?.running) return <span className={cn(cls, "text-zinc-700")}><Loader2 className="h-3.5 w-3.5 animate-spin" /> Running</span>;
  if (s?.waiting) return <span className={cn(cls, "font-medium text-amber-700")}><ShieldAlert className="h-3.5 w-3.5" /> Waiting for you</span>;
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
  if (s?.published) extras.push(<span key="p" className="inline-flex items-center gap-1"><Globe className="h-3 w-3" /> Published</span>);
  if (!item.mine) extras.push(<span key="m" className="inline-flex items-center gap-1" title="Shared by a teammate"><Users className="h-3 w-3" /> Shared</span>);
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
      className={cn("flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors @3xl:items-center", GRID, active ? "bg-zinc-100" : "hover:bg-zinc-50")}
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
            className="block max-w-full truncate text-left text-sm font-medium text-zinc-900 cursor-pointer"
          >
            {item.name}
          </button>
          {/* Narrow: the columns, folded into one line. */}
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-500 @3xl:hidden">
            <StatusLabel s={s} className="inline-flex text-xs" />
            {lastRun}
            {s?.runs ? <span className="tabular-nums">{s.runs} runs{rate !== null ? `, ${Math.round(rate * 100)}%` : ""}</span> : null}
          </p>
          {extras.length > 0 && <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-500">{extras}</p>}
        </div>
      </div>
      <StatusLabel s={s} className="hidden @3xl:flex" />
      <span className="hidden text-sm text-zinc-700 @3xl:block">{lastRun}</span>
      <span className="hidden text-right text-sm tabular-nums text-zinc-700 @3xl:block">{s?.runs || "—"}</span>
      <span className="hidden text-right text-sm tabular-nums text-zinc-700 @3xl:block">{rate !== null ? `${Math.round(rate * 100)}%` : "—"}</span>
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
