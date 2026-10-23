"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Copy, Pencil, Plus, Search, ShieldAlert, Trash2, Unlink, Wrench, X } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Select } from "@/components/builder/fields";
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
  read: { label: "Read", hint: "Only looks things up", Icon: Search, pill: "bg-zinc-100 text-zinc-600" },
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
      <p className="text-sm text-zinc-500">
        <span className="font-medium text-zinc-900 tabular-nums">{connected.length}</span> of {servers.length} connected
        <span className="mx-2" aria-hidden>·</span>
        <span className="font-medium text-zinc-900 tabular-nums">{totalTools.toLocaleString()}</span> tools
        <span className="mx-2" aria-hidden>·</span>
        <span className="font-medium text-zinc-900 tabular-nums">{agentLinks}</span> in use by agents
      </p>

      <div className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative flex-1 sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input className="pl-9" placeholder={`Search ${servers.length} connectors`} value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search connectors" />
          </div>
          <Select className="sm:w-44" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort by">
            {Object.entries(SORTS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </Select>
        </div>
        {/* One row that scrolls sideways on a phone instead of wrapping into a block. */}
        <div className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist" aria-label="Category">
          {["All", ...Object.keys(CATEGORIES)].map((c) => (
            <button
              key={c}
              type="button"
              role="tab"
              aria-selected={category === c}
              onClick={() => setCategory(c)}
              className={cn(
                "shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer",
                category === c ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900",
              )}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {groups.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-10 text-center text-sm text-zinc-500">No connectors match your search.</p>
      ) : (
        <div className="space-y-8">
          {groups.map((g) => (
            <section key={g.label} className="space-y-3">
              <h2 className="text-base font-semibold text-zinc-900">
                {g.label} <span className="font-normal text-zinc-500">· {g.items.length}</span>
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {g.items.map((s) => {
                  const uses = usedBy[s.id] ?? 0;
                  return (
                    <li key={s.id} className="flex">
                      <div
                        className={cn(
                          "flex w-full flex-col gap-3 rounded-lg border p-4 transition-colors",
                          open === s.id ? "border-[var(--accent-border)]" : "border-zinc-200 hover:border-zinc-300",
                        )}
                      >
                        <button type="button" onClick={() => setOpen(s.id)} className="flex flex-1 items-start gap-3 text-left cursor-pointer" title={`See ${s.name}'s tools`}>
                          <ConnectorIcon name={s.name} size="sm" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-zinc-900">{s.name}</span>
                            {s.description && <span className="mt-0.5 line-clamp-2 block text-xs text-zinc-500">{s.description}</span>}
                          </span>
                        </button>
                        <div className="flex items-center justify-between gap-2">
                          {s.connected ? (
                            <span className="flex min-w-0 items-center gap-1.5 text-xs text-zinc-500">
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--success)]" aria-hidden />
                              <span className="truncate">
                                Connected · {s.bound_tools.length} tool{s.bound_tools.length === 1 ? "" : "s"}
                                {uses ? ` · ${uses} agent${uses === 1 ? "" : "s"}` : ""}
                              </span>
                            </span>
                          ) : (
                            <span className="text-xs text-zinc-500">Not connected</span>
                          )}
                          {s.connected ? (
                            <button type="button" onClick={() => setOpen(s.id)} className="shrink-0 text-sm font-medium text-zinc-700 hover:text-zinc-900 cursor-pointer">
                              Manage
                            </button>
                          ) : (
                            <Button size="sm" variant="outline" className="shrink-0" onClick={() => setConnecting(s.id)} aria-label={`Connect ${s.name}`}>
                              <Plus /> Connect
                            </Button>
                          )}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}

      {openServer && (
        <ToolsPanel
          server={openServer}
          uses={usedBy[openServer.id] ?? 0}
          token={token}
          onConnect={() => setConnecting(openServer.id)}
          disconnecting={disconnect.isPending && disconnect.variables?.id === openServer.id}
          onDisconnect={() =>
            confirm(`Disconnect "${openServer.name}"? Agents that use it stop working until you connect again.`) &&
            disconnect.mutate(openServer, { onSuccess: () => setOpen(null) })
          }
          onClose={() => setOpen(null)}
        />
      )}
      {disconnect.isError && <p className="text-sm text-red-600">Couldn&apos;t disconnect. Try again.</p>}
      {connecting && (
        <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />
      )}
    </div>
  );
}

type Tool = ServerTools["tools"][number];

/** The side panel: a connector's tools and what each one can do, nothing else. */
function ToolsPanel({
  server, uses, token, onConnect, onDisconnect, disconnecting, onClose,
}: {
  server: MCPServerEntry;
  uses: number;
  token: string;
  onConnect: () => void;
  onDisconnect: () => void;
  disconnecting: boolean;
  onClose: () => void;
}) {
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
      <div className="relative flex h-dvh w-full max-w-lg flex-col border-l border-zinc-200 bg-[var(--surface)] shadow-2xl">
        <div className="flex items-start gap-3 border-b border-zinc-100 p-4 sm:p-5">
          <ConnectorIcon name={server.name} size="sm" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-base font-semibold text-zinc-900">{server.name}</h2>
            </div>
            {server.description && <p className="mt-0.5 line-clamp-2 text-sm text-zinc-500">{server.description}</p>}
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
              <span className="inline-flex items-center gap-1.5">
                <span className={cn("h-1.5 w-1.5 rounded-full", server.connected ? "bg-[var(--success)]" : "bg-zinc-400")} aria-hidden />
                {server.connected ? "Connected" : "Not connected"}
              </span>
              <span>{uses ? `Used by ${uses} agent${uses === 1 ? "" : "s"}` : "Not used by any agent yet"}</span>
            </p>
            <div className="mt-3">
              {server.connected ? (
                <Button size="sm" variant="danger" disabled={disconnecting} onClick={onDisconnect}>
                  {disconnecting ? <Spinner className="h-4 w-4" /> : <Unlink />} Disconnect
                </Button>
              ) : (
                <Button size="sm" onClick={onConnect}><Plus /> Connect</Button>
              )}
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 border-b border-zinc-100 px-4 py-4 sm:px-5">
          <h3 className="text-sm font-semibold text-zinc-900">
            Tools {!tools.isLoading && <span className="font-normal text-zinc-500">· {list.length}</span>}
          </h3>
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
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                <Input className="pl-9" placeholder={`Search ${list.length} tools`} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search tools" />
              </div>
              {counts.edit + counts.delete > 0 && (
                <p className="flex items-start gap-1.5 text-xs text-zinc-500">
                  <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0 text-amber-700" />
                  Tools that edit or delete data ask you first before they run, unless an agent is set up otherwise.
                </p>
              )}
            </>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
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
        "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
        on ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900",
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
    <li className="rounded-lg border border-zinc-200 p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="break-all font-mono text-xs font-medium text-zinc-900">{tool.name}</span>
            <span className={cn("inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs font-medium", R.pill)} title={R.hint}>
              <R.Icon className="h-3 w-3" /> {R.label}
            </span>
          </div>
          {tool.description && <p className={cn("mt-1 text-sm text-zinc-500", !open && "line-clamp-3")}>{tool.description}</p>}
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
          className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer"
        >
          {copied ? <Check className="h-4 w-4 text-emerald-700" /> : <Copy className="h-4 w-4" />}
        </button>
      </div>
      {(params.length > 0 || long) && (
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-zinc-700 hover:text-zinc-900 cursor-pointer">
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
          {open ? "Less" : params.length ? `${params.length} input${params.length === 1 ? "" : "s"}` : "More"}
        </button>
      )}
      {open && params.length > 0 && (
        <ul className="mt-2 divide-y divide-zinc-100 rounded-md bg-zinc-50">
          {params.map((p) => (
            <li key={p.name} className="px-2.5 py-1.5">
              <p className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-mono font-medium text-zinc-900">{p.name}</span>
                <span className="text-zinc-500">{p.type}</span>
                {p.required && <span className="rounded bg-zinc-100 px-1 text-xs font-medium text-zinc-600">required</span>}
              </p>
              {p.description && <p className="mt-0.5 text-xs text-zinc-500">{p.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
