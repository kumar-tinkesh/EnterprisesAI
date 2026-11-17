"use client";

import { useEffect, useState } from "react";
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { CheckCircle2, Plus, Search, Server } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { RiskBadge } from "@/components/builder/fields";
import { ConnectButton, useConnectedServers, useServerStatus } from "@/components/connections/connect-button";
import { vendorApi } from "@/lib/api";
import { serverCandidates } from "@/lib/builder/agent-wizard";
import { builderApi } from "@/lib/builder/api";
import type { ServerTools, ToolCandidate } from "@/lib/builder/types";

const MAX_SERVERS = 5;

type ServerToolList = { id: string; query: UseQueryResult<ServerTools> };

/** Each server's whole tool list (shared cache, so a picker and a suggestion list load it once). Servers that
 *  turn out to have no tools are left out. */
export function useServerToolLists(token: string, serverIds: string[]): ServerToolList[] {
  const lists = useQueries({
    queries: serverIds.map((id) => ({
      queryKey: ["builder-server-tools", token, id],
      queryFn: () => builderApi.serverTools(token, id),
      enabled: !!token,
      staleTime: 60_000,
    })),
  });
  return serverIds
    .map((id, i) => ({ id, query: lists[i] }))
    .filter((s) => !s.query.isSuccess || s.query.data.tools.length > 0);
}

/** One row per app: its tool count, Connect when it isn't connected, and "Add all tools". */
export function AppRows({
  token,
  servers,
  exclude,
  onPickMany,
}: {
  token: string;
  servers: ServerToolList[];
  exclude: string[];
  onPickMany: (tools: ToolCandidate[]) => void;
}) {
  const status = useServerStatus(token);
  return (
    <ul className="space-y-1">
      {servers.map(({ id, query: st }) => {
        const name = st.data?.server_name ?? (status.loaded ? status.name(id) : "…");
        const all = st.data ? serverCandidates(st.data) : [];
        const missing = all.filter((t) => !exclude.includes(t.tool_id));
        const connected = status.isConnected(id, st.data?.connected ?? false);
        return (
          <li key={id} className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 px-2.5 py-2">
            <Server className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 truncate text-xs font-semibold text-zinc-900">
                {name}
                {connected && <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-600" aria-label="Connected" />}
              </p>
              {st.data && <p className="text-xs text-zinc-500">{all.length} tool{all.length === 1 ? "" : "s"}</p>}
            </div>
            {!connected && st.data && <ConnectButton serverId={id} token={token} className="py-1" />}
            {st.isLoading ? (
              <Spinner className="h-4 w-4 text-zinc-400" />
            ) : st.isError ? (
              <span className="text-xs text-red-600">Couldn&apos;t load its tools</span>
            ) : missing.length === 0 ? (
              <span className="flex shrink-0 items-center gap-0.5 text-xs text-emerald-600">
                <CheckCircle2 className="h-3 w-3" /> All added
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onPickMany(missing)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-zinc-50 cursor-pointer"
              >
                <Plus className="h-3 w-3" />
                {missing.length === all.length ? `Add all ${all.length} tools` : `Add ${missing.length} more`}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Find a tool by describing what it should do — the backend's hybrid search
 * (meaning + keywords + reranker) over the tools this user may use.
 *
 * With ``onPickMany``, the MCP servers behind the results (and any whose name
 * matches the search) are listed too, each with "Add all tools": every tool
 * that server has, not only the ones the search surfaced.
 */
export function ToolPicker({
  token,
  onPick,
  onPickMany,
  initialQuery = "",
  exclude = [],
}: {
  token: string;
  onPick: (tool: ToolCandidate) => void;
  onPickMany?: (tools: ToolCandidate[]) => void;
  initialQuery?: string;
  exclude?: string[];
}) {
  const [text, setText] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);

  useEffect(() => {
    const t = setTimeout(() => setQuery(text.trim()), 350);
    return () => clearTimeout(t);
  }, [text]);

  const searching = !!token && query.length >= 2;
  const results = useQuery({
    queryKey: ["builder-tool-search", query],
    queryFn: () => builderApi.searchTools(token, query, 8),
    enabled: searching,
    staleTime: 30_000,
  });
  // The same catalog query the connect buttons read, so it's usually cached already.
  const catalog = useQuery({
    queryKey: ["catalog", token, ""],
    queryFn: () => vendorApi.getCatalog(token),
    enabled: !!token && !!onPickMany,
    staleTime: 30_000,
  });

  const items = (results.data ?? []).filter((t) => !exclude.includes(t.tool_id));
  const isConnected = useConnectedServers(token);

  // Servers named like the search first, then the ones behind the matching tools.
  const q = query.toLowerCase();
  const serverIds = !onPickMany || !searching ? [] : Array.from(new Set([
    ...(catalog.data?.servers ?? []).filter((s) => s.name.toLowerCase().includes(q)).map((s) => s.id),
    ...(results.data ?? []).map((t) => t.server_id),
  ])).slice(0, MAX_SERVERS);
  const servers = useServerToolLists(token, serverIds);

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <Input
          className="h-9 pl-8"
          placeholder={onPickMany ? "Search an app (e.g. Slack) or describe what it should do" : "Describe what it should do, e.g. send a Slack message"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {results.isFetching && <Spinner className="h-4 w-4 text-zinc-400" />}
      {results.isError && <p className="text-xs text-red-600">Tool search failed.</p>}
      {searching && !results.isFetching && items.length === 0 && servers.length === 0 && (
        <p className="text-xs text-zinc-400">No tools match. Your admin may need to add or grant an MCP server.</p>
      )}

      {servers.length > 0 && onPickMany && (
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Apps (MCP servers)</p>
          <AppRows token={token} servers={servers} exclude={exclude} onPickMany={onPickMany} />
          {items.length > 0 && <p className="pt-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Single tools</p>}
        </div>
      )}

      <ul className="max-h-64 space-y-1 overflow-y-auto">
        {items.map((t) => {
          const connected = isConnected(t.server_id, t.connected);
          return (
            <li key={t.tool_id} className="flex items-start gap-1.5 rounded-lg border border-zinc-200 hover:border-indigo-300 hover:bg-indigo-50/40">
              <button type="button" onClick={() => onPick(t)} className="min-w-0 flex-1 px-2.5 py-2 text-left cursor-pointer">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs font-semibold text-zinc-900">
                    {t.server_name}.{t.tool_name}
                  </span>
                  <RiskBadge risk={t.risk} />
                  {connected && (
                    <span className="ml-auto flex shrink-0 items-center gap-0.5 text-xs text-emerald-600">
                      <CheckCircle2 className="h-3 w-3" /> connected
                    </span>
                  )}
                </div>
                {t.description && <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">{t.description}</p>}
              </button>
              {!connected && <ConnectButton serverId={t.server_id} token={token} className="m-2 ml-0" />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
