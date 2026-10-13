"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, ChevronDown, Copy, Pencil, Plus, Search, ShieldAlert, Trash2, Unlink, Wrench, X } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Spinner } from "@/components/ui/spinner";
import { ConnectServerDialog } from "@/components/connections/server-connect";
import { ConnectorIcon, connectorKey } from "@/components/connections/connector-icon";
import { vendorApi, type MCPServerEntry } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { serverIdOf } from "@/lib/builder/graph";
import type { Risk, ServerTools } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const SORTS = { az: "Name (A–Z)", most_used: "Most used", least_used: "Least used", tools: "Most tools" } as const;
type SortKey = keyof typeof SORTS;

/** Categories by icon key (see connector-icon); anything unmatched is only under "All". */
const CATEGORIES: Record<string, string[]> = {
  Productivity: ["notion", "google_sheets", "quickbooks_pro", "filesystem"],
  Communication: ["slack", "gmail", "whatsapp"],
  "Developer Tools": ["github", "atlassian", "jira", "linear"],
  "Data & Web Search": ["wikipedia", "wikidata", "gleif", "news_mcp", "job_search_mcp", "tavily", "firecrawl", "travelpayouts"],
  "Custom MCP": ["custom_mcp_server"],
};

const RISK: Record<Risk, { label: string; hint: string; Icon: typeof Wrench; pill: string }> = {
  read: { label: "Read", hint: "Only looks things up", Icon: Search, pill: "bg-sky-50 text-sky-700" },
  edit: { label: "Edit", hint: "Creates or changes data", Icon: Pencil, pill: "bg-amber-50 text-amber-700" },
  delete: { label: "Delete", hint: "Removes data", Icon: Trash2, pill: "bg-red-50 text-red-700" },
};

export default function ConnectorsPage() {
  return (
    <ProtectedDashboard path="/user" title="Connectors" description="Connect your apps once and every agent you build can use their tools.">
      <Connectors />
    </ProtectedDashboard>
  );
}

function Connectors() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog", token, ""], queryFn: () => vendorApi.getCatalog(token), enabled: !!token });
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("az");
  const [category, setCategory] = useState("All");
  const [open, setOpen] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);

  const disconnect = useMutation({
    mutationFn: (s: MCPServerEntry) =>
      s.auth_type === "device_pairing" ? vendorApi.disconnectBridgeAsUser(token, s.id) : vendorApi.disconnectMCPServerAsUser(token, s.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["catalog", token] }),
  });

  const servers = catalog.data?.servers ?? [];
  // Agents using each connector: any of its tools in the agent's tool list.
  const usedBy = useMemo(() => {
    const out: Record<string, number> = {};
    for (const a of agents.data ?? []) {
      for (const sid of new Set((a.config.tool_ids ?? []).map(serverIdOf).filter(Boolean) as string[])) out[sid] = (out[sid] ?? 0) + 1;
    }
    return out;
  }, [agents.data]);

  const shown = servers
    .filter((s) => {
      if (category !== "All" && !CATEGORIES[category]?.includes(connectorKey(s.name) ?? "")) return false;
      const q = query.trim().toLowerCase();
      return !q || s.name.toLowerCase().includes(q) || (s.description ?? "").toLowerCase().includes(q);
    })
    .sort((a, b) => {
      const ua = usedBy[a.id] ?? 0;
      const ub = usedBy[b.id] ?? 0;
      if (sort === "most_used") return ub - ua || a.name.localeCompare(b.name);
      if (sort === "least_used") return ua - ub || a.name.localeCompare(b.name);
      if (sort === "tools") return b.bound_tools.length - a.bound_tools.length || a.name.localeCompare(b.name);
      return a.name.localeCompare(b.name);
    });
  const groups = [
    { label: "Connected", items: shown.filter((s) => s.connected) },
    { label: "Not connected", items: shown.filter((s) => !s.connected) },
  ].filter((g) => g.items.length);

  const connected = servers.filter((s) => s.connected);
  const totalTools = connected.reduce((n, s) => n + s.bound_tools.length, 0);
  const agentLinks = connected.reduce((n, s) => n + (usedBy[s.id] ?? 0), 0);
  const openServer = servers.find((s) => s.id === open) ?? null;

  if (catalog.isLoading) return <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-zinc-400" /></div>;
  if (catalog.isError) {
    return <p className="mt-6 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">Couldn&apos;t load your connectors. Refresh the page, or sign out and back in.</p>;
  }
  if (servers.length === 0) return <p className="mt-6 text-sm text-zinc-500">No connectors yet. Ask your admin to add one.</p>;

  return (
    <div className="mt-6 space-y-6">
      <div className="grid grid-cols-3 gap-3">
        <Metric label="Active connections" value={connected.length} sub={`of ${servers.length} available`} />
        <Metric label="Total tools" value={totalTools} sub="ready for your agents" />
        <Metric label="Agent connections" value={agentLinks} sub="agents × connectors in use" />
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[12rem] max-w-sm flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <input
              className="h-9 w-full rounded-lg border border-zinc-200 bg-white pl-9 pr-3 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-indigo-400 focus:outline-none"
              placeholder={`Search ${servers.length} connectors…`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search connectors"
            />
          </div>
          <label className="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
            Sort by
            <select className="h-9 rounded-lg border border-zinc-200 bg-white px-2 text-sm text-zinc-900" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              {Object.entries(SORTS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Category">
          {["All", ...Object.keys(CATEGORIES)].map((c) => (
            <button
              key={c}
              type="button"
              role="tab"
              aria-selected={category === c}
              onClick={() => setCategory(c)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-xs font-medium cursor-pointer",
                category === c ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "border-zinc-200 bg-white text-zinc-600 hover:text-zinc-900",
              )}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-zinc-500">No connectors match your search.</p>
      ) : (
        <div className="space-y-8">
          {groups.map((g) => (
            <div key={g.label}>
              <div className="mb-3 flex items-center gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{g.label}</h2>
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-500">{g.items.length}</span>
                <span className="h-px flex-1 bg-zinc-100" />
              </div>
              <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {g.items.map((s) => {
                  const uses = usedBy[s.id] ?? 0;
                  const busy = disconnect.isPending && disconnect.variables?.id === s.id;
                  return (
                    <li key={s.id} className="group relative">
                      <button
                        type="button"
                        onClick={() => setOpen(s.id)}
                        className={cn(
                          "flex h-full w-full items-start gap-4 rounded-2xl border bg-white p-5 text-left transition hover:border-indigo-300 cursor-pointer",
                          open === s.id ? "border-indigo-400" : "border-zinc-200",
                        )}
                        title={`See ${s.name}'s tools`}
                      >
                        <ConnectorIcon name={s.name} />
                        <span className="min-w-0 flex-1 pr-14">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-zinc-900">{s.name}</span>
                          </span>
                          {s.description && <span className="mt-1 line-clamp-2 block text-xs text-zinc-500">{s.description}</span>}
                          <span className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-500">
                            {s.connected ? (
                              <>
                                <span className="font-medium text-zinc-600">{s.bound_tools.length} tool{s.bound_tools.length === 1 ? "" : "s"}</span>
                                <span aria-hidden>•</span>
                                <span className={uses ? "text-indigo-600" : ""}>{uses ? `Used by ${uses} agent${uses === 1 ? "" : "s"}` : "Not used by any agent yet"}</span>
                              </>
                            ) : (
                              <span>Connect it to let your agents use its tools</span>
                            )}
                          </span>
                        </span>
                      </button>
                      <div className="absolute right-4 top-4 flex items-center gap-1">
                        {s.connected ? (
                          <>
                            <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700">Connected</span>
                            <button
                              type="button"
                              aria-label={`Disconnect ${s.name}`}
                              title="Disconnect"
                              disabled={busy}
                              onClick={() => confirm(`Disconnect "${s.name}"? Agents that use it stop working until you connect again.`) && disconnect.mutate(s)}
                              className="rounded-md p-1 text-zinc-400 opacity-0 transition hover:text-red-600 focus:opacity-100 group-hover:opacity-100 disabled:opacity-50 cursor-pointer"
                            >
                              {busy ? <Spinner className="h-4 w-4" /> : <Unlink className="h-4 w-4" />}
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConnecting(s.id)}
                            title={`Connect ${s.name}`}
                            aria-label={`Connect ${s.name}`}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm hover:bg-indigo-500 cursor-pointer"
                          >
                            <Plus className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}

      {openServer && (
        <ToolsPanel
          server={openServer}
          uses={usedBy[openServer.id] ?? 0}
          token={token}
          onConnect={() => setConnecting(openServer.id)}
          onClose={() => setOpen(null)}
        />
      )}
      {connecting && (
        <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />
      )}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
      <p className="text-2xl font-bold tabular-nums text-zinc-900">{value.toLocaleString()}</p>
      <p className="mt-1 text-xs font-medium text-zinc-600">{label}</p>
      <p className="hidden text-[11px] text-zinc-500 sm:block">{sub}</p>
    </div>
  );
}

type Tool = ServerTools["tools"][number];

/** The side panel: a connector's tools and what each one can do, nothing else. */
function ToolsPanel({ server, uses, token, onConnect, onClose }: { server: MCPServerEntry; uses: number; token: string; onConnect: () => void; onClose: () => void }) {
  const tools = useQuery({ queryKey: ["builder-server-tools", server.id], queryFn: () => builderApi.serverTools(token, server.id), enabled: !!token, staleTime: 30_000 });
  const [q, setQ] = useState("");
  const [risk, setRisk] = useState<Risk | "all">("all");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    setQ("");
    setRisk("all");
  }, [server.id]);

  const list = tools.data?.tools ?? [];
  const counts = { read: 0, edit: 0, delete: 0 } as Record<Risk, number>;
  for (const t of list) counts[t.risk.risk] = (counts[t.risk.risk] ?? 0) + 1;
  const needle = q.trim().toLowerCase();
  const shown = list.filter(
    (t) => (risk === "all" || t.risk.risk === risk) && (!needle || t.name.toLowerCase().includes(needle) || (t.description ?? "").toLowerCase().includes(needle)),
  );

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={`${server.name}: tools and capabilities`}>
      <button type="button" aria-label="Close" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-lg flex-col border-l border-zinc-200 bg-white shadow-2xl">
        <div className="flex items-start gap-3 border-b border-zinc-100 p-5">
          <ConnectorIcon name={server.name} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-base font-semibold text-zinc-900">{server.name}</h2>
            </div>
            {server.description && <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">{server.description}</p>}
            <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
              {server.connected ? (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">connected</span>
              ) : (
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 font-medium text-zinc-600">not connected</span>
              )}
              <span className="inline-flex items-center gap-1 text-zinc-500">
                <Bot className="h-3 w-3" /> {uses ? `Used by ${uses} agent${uses === 1 ? "" : "s"}` : "Not used by any agent yet"}
              </span>
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 border-b border-zinc-100 px-5 py-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900"><Wrench className="h-4 w-4 text-zinc-400" /> Tools &amp; capabilities</h3>
            {!tools.isLoading && <span className="text-xs text-zinc-500">{list.length} tool{list.length === 1 ? "" : "s"}</span>}
          </div>
          {!server.connected && (
            <div className="flex items-center gap-3 rounded-lg border border-indigo-100 bg-indigo-50 p-3">
              <p className="flex-1 text-xs text-indigo-700">Connect {server.name} so your agents can use these tools.</p>
              <button type="button" onClick={onConnect} className="inline-flex shrink-0 items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 cursor-pointer">
                <Plus className="h-3.5 w-3.5" /> Connect
              </button>
            </div>
          )}
          {list.length > 0 && (
            <>
              {/* What it can do, at a glance; each chip filters the list. */}
              <div className="flex flex-wrap gap-1.5">
                <Chip on={risk === "all"} onClick={() => setRisk("all")}>All {list.length}</Chip>
                {(Object.keys(RISK) as Risk[]).filter((r) => counts[r]).map((r) => {
                  const R = RISK[r];
                  return (
                    <Chip key={r} on={risk === r} onClick={() => setRisk(risk === r ? "all" : r)} title={R.hint}>
                      <R.Icon className="h-3 w-3" /> {R.label} {counts[r]}
                    </Chip>
                  );
                })}
              </div>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
                <input
                  className="h-8 w-full rounded-lg border border-zinc-200 bg-white pl-8 pr-3 text-xs text-zinc-900 placeholder:text-zinc-400 focus:border-indigo-400 focus:outline-none"
                  placeholder={`Search ${list.length} tools…`}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  aria-label="Search tools"
                />
              </div>
              {counts.edit + counts.delete > 0 && (
                <p className="flex items-start gap-1.5 text-[11px] text-zinc-500">
                  <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0 text-amber-600" />
                  Tools that edit or delete data ask you first before they run, unless an agent is set up otherwise.
                </p>
              )}
            </>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {tools.isLoading ? (
            <div className="flex justify-center py-10"><Spinner className="h-5 w-5 text-zinc-400" /></div>
          ) : tools.isError ? (
            <p className="rounded-lg bg-red-50 p-3 text-xs text-red-700">Couldn&apos;t load this connector&apos;s tools. {server.connected ? "Try again in a moment." : "It may need to be connected first."}</p>
          ) : list.length === 0 ? (
            <p className="py-10 text-center text-sm text-zinc-500">{server.connected ? "This connector doesn't offer any tools." : "Its tools appear once it's connected."}</p>
          ) : shown.length === 0 ? (
            <p className="py-10 text-center text-sm text-zinc-500">No tools match.</p>
          ) : (
            <ul className="space-y-2">
              {shown.map((t) => <ToolCard key={t.name} tool={t} />)}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function Chip({ on, onClick, title, children }: { on: boolean; onClick: () => void; title?: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={on}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium cursor-pointer",
        on ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "border-zinc-200 bg-white text-zinc-600 hover:text-zinc-900",
      )}
    >
      {children}
    </button>
  );
}

type Param = { name: string; type: string; required: boolean; description?: string };

function paramsOf(schema: Record<string, unknown> | null): Param[] {
  const props = (schema?.properties ?? {}) as Record<string, { type?: string | string[]; description?: string; enum?: unknown[] }>;
  const required = new Set((schema?.required as string[] | undefined) ?? []);
  return Object.entries(props).map(([name, p]) => ({
    name,
    type: p.enum ? "one of" : Array.isArray(p.type) ? p.type.join(" | ") : p.type ?? "any",
    required: required.has(name),
    description: p.description,
  }));
}

function ToolCard({ tool }: { tool: Tool }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const R = RISK[tool.risk.risk] ?? RISK.read;
  const params = paramsOf(tool.input_schema);
  const long = (tool.description ?? "").length > 160;

  return (
    <li className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-xs font-semibold text-zinc-900">{tool.name}</span>
            <span className={cn("inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium", R.pill)} title={R.hint}>
              <R.Icon className="h-2.5 w-2.5" /> {R.label}
            </span>
          </div>
          {tool.description && <p className={cn("mt-1 text-[11px] leading-relaxed text-zinc-600", !open && "line-clamp-3")}>{tool.description}</p>}
        </div>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(tool.name);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
          aria-label={`Copy ${tool.name}`}
          title="Copy the tool's name"
          className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      {(params.length > 0 || long) && (
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer">
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
          {open ? "Less" : params.length ? `${params.length} input${params.length === 1 ? "" : "s"}` : "More"}
        </button>
      )}
      {open && params.length > 0 && (
        <ul className="mt-2 divide-y divide-zinc-100 rounded-lg border border-zinc-200 bg-white">
          {params.map((p) => (
            <li key={p.name} className="px-2.5 py-1.5">
              <p className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="font-mono font-medium text-zinc-900">{p.name}</span>
                <span className="text-zinc-500">{p.type}</span>
                {p.required && <span className="rounded bg-zinc-100 px-1 text-[10px] font-medium text-zinc-600">required</span>}
              </p>
              {p.description && <p className="mt-0.5 text-[11px] text-zinc-500">{p.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
