"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { RiskBadge } from "@/components/builder/fields";
import { ConnectButton, useConnectedServers } from "@/components/connections/connect-button";
import { builderApi } from "@/lib/builder/api";
import type { ToolCandidate } from "@/lib/builder/types";

/**
 * Find a tool by describing what it should do — the backend's hybrid search
 * (meaning + keywords + reranker) over the tools this user may use.
 */
export function ToolPicker({
  token,
  onPick,
  initialQuery = "",
  exclude = [],
}: {
  token: string;
  onPick: (tool: ToolCandidate) => void;
  initialQuery?: string;
  exclude?: string[];
}) {
  const [text, setText] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);

  useEffect(() => {
    const t = setTimeout(() => setQuery(text.trim()), 350);
    return () => clearTimeout(t);
  }, [text]);

  const results = useQuery({
    queryKey: ["builder-tool-search", query],
    queryFn: () => builderApi.searchTools(token, query, 8),
    enabled: !!token && query.length >= 2,
    staleTime: 30_000,
  });

  const items = (results.data ?? []).filter((t) => !exclude.includes(t.tool_id));
  const isConnected = useConnectedServers(token);

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <Input
          className="h-9 pl-8"
          placeholder="Describe what it should do, e.g. send a Slack message"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {results.isFetching && <Spinner className="h-4 w-4 text-zinc-400" />}
      {results.isError && <p className="text-xs text-red-600">Tool search failed.</p>}
      {query.length >= 2 && !results.isFetching && items.length === 0 && (
        <p className="text-xs text-zinc-400">No tools match. Your admin may need to add or grant an MCP server.</p>
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
                    <span className="ml-auto flex shrink-0 items-center gap-0.5 text-[10px] text-emerald-600">
                      <CheckCircle2 className="h-3 w-3" /> connected
                    </span>
                  )}
                </div>
                {t.description && <p className="mt-0.5 line-clamp-2 text-[11px] text-zinc-500">{t.description}</p>}
              </button>
              {!connected && <ConnectButton serverId={t.server_id} token={token} className="m-2 ml-0" />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
