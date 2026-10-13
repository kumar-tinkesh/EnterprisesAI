"use client";

import { CheckCircle2, Plug, Plus, Unlink } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Spinner } from "@/components/ui/spinner";
import { ConnectServerDialog } from "@/components/connections/server-connect";
import { vendorApi, type MCPServerEntry } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

export default function ConnectorsPage() {
  return (
    <ProtectedDashboard path="/user" title="Connectors" description="Connect an app once and every agent you build can use its tools.">
      <Connectors />
    </ProtectedDashboard>
  );
}

/** Every MCP server the admin has made available to this user. Clicking one
 *  connects it right here (credentials, sign-in or QR, whatever it needs). */
function Connectors() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [connecting, setConnecting] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["catalog", token, ""],
    queryFn: () => vendorApi.getCatalog(token),
    enabled: !!token,
  });
  const disconnect = useMutation({
    mutationFn: (s: MCPServerEntry) =>
      s.auth_type === "device_pairing" ? vendorApi.disconnectBridgeAsUser(token, s.id) : vendorApi.disconnectMCPServerAsUser(token, s.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["catalog", token] }),
  });
  const servers = data?.servers ?? [];
  const groups = [
    { label: "Connected", items: servers.filter((s) => s.connected) },
    { label: "Not connected", items: servers.filter((s) => !s.connected) },
  ].filter((g) => g.items.length);

  return (
    <section className="mt-4 rounded-xl border border-zinc-200 bg-white p-4 sm:p-6" aria-labelledby="connectors-heading">
      <div className="flex items-center gap-2">
        <Plug className="h-5 w-5 shrink-0 text-sky-600" />
        <div>
          <h2 id="connectors-heading" className="text-lg font-semibold text-zinc-900">Connectors you can use</h2>
          <p className="text-sm text-zinc-500">Connect an app once and every agent you build can use its tools.</p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-6">
          <Spinner className="h-5 w-5 text-zinc-500" />
        </div>
      ) : isError ? (
        <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">
          Couldn&apos;t load your connectors. Refresh the page, or sign out and back in.
        </p>
      ) : servers.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-400">No connectors yet. Ask your admin to add one.</p>
      ) : (
        <div className="mt-4 space-y-5">
          {groups.map((g) => (
            <div key={g.label}>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{g.label}</h3>
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-500">{g.items.length}</span>
                <span className="h-px flex-1 bg-zinc-100" />
              </div>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {g.items.map((s) => (
                  <li key={s.id} className="flex min-w-0 items-stretch rounded-lg border border-zinc-200 transition-colors hover:border-sky-300 hover:bg-zinc-50">
                    <button
                      type="button"
                      onClick={() => setConnecting(s.id)}
                      title={s.connected ? `Reconnect ${s.name} or update its credentials` : `Connect ${s.name}`}
                      className="flex min-w-0 flex-1 flex-col p-3 text-left cursor-pointer"
                    >
                      <span className="flex w-full items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-sm font-medium text-zinc-900">{s.name}</span>
                        {s.connected ? (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                            <CheckCircle2 className="h-3 w-3" /> Connected
                          </span>
                        ) : (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-sky-600 px-2 py-1 text-xs font-medium text-white">
                            <Plus className="h-3 w-3" /> Connect
                          </span>
                        )}
                      </span>
                      {s.description && <span className="mt-1 line-clamp-2 text-xs text-zinc-500">{s.description}</span>}
                      {s.connected && (
                        <span className="mt-2 text-[11px] text-zinc-400">
                          {s.bound_tools.length} tool{s.bound_tools.length === 1 ? "" : "s"} ready for your agents
                        </span>
                      )}
                    </button>
                    {s.connected && (
                      <button
                        type="button"
                        aria-label={`Disconnect ${s.name}`}
                        title="Disconnect"
                        disabled={disconnect.isPending && disconnect.variables?.id === s.id}
                        onClick={() => {
                          if (confirm(`Disconnect "${s.name}"? Agents that use it stop working until you connect again.`)) disconnect.mutate(s);
                        }}
                        className="shrink-0 self-start p-3 text-zinc-400 hover:text-red-600 disabled:opacity-50 cursor-pointer"
                      >
                        {disconnect.isPending && disconnect.variables?.id === s.id ? <Spinner className="h-4 w-4" /> : <Unlink className="h-4 w-4" />}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {connecting && (
        <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />
      )}
    </section>
  );
}
