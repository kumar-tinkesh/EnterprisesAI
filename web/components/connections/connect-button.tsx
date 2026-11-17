"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link2 } from "lucide-react";

import { ConnectServerDialog } from "@/components/connections/server-connect";
import { vendorApi } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Which servers this user has connected, from the same catalog query the
 * connect dialog refreshes — so anything reading it updates the moment a
 * connection succeeds, wherever it was made. ``fallback`` is used until the
 * catalog has loaded (e.g. the ``connected`` flag a tool search returned).
 */
export function useConnectedServers(token: string) {
  return useServerStatus(token).isConnected;
}

/** The same catalog, by server: whether this user (not the admin) has connected it, and its name. */
export function useServerStatus(token: string) {
  const catalog = useQuery({
    queryKey: ["catalog", token, ""],
    queryFn: () => vendorApi.getCatalog(token),
    enabled: !!token,
    staleTime: 30_000,
  });
  const servers = new Map((catalog.data?.servers ?? []).map((s) => [s.id, s]));
  return {
    loaded: !!catalog.data,
    isConnected: (serverId: string, fallback = false) => (catalog.data ? !!servers.get(serverId)?.connected : fallback),
    /** Not in this user's catalog: deleted by the admin, or no longer granted — connecting can't help. */
    isGone: (serverId: string) => !!catalog.data && !servers.has(serverId),
    name: (serverId: string) => servers.get(serverId)?.name ?? "A removed system",
  };
}

/**
 * The servers among ``toolIds`` this user can't use yet, each with its tools: not connected
 * (``removed`` false — a Connect fixes it) or gone from their catalog (``removed`` — the tools
 * have to be picked again). Empty until the catalog loads, and for tools that aren't MCP tools.
 */
export function useMissingServers(token: string, toolIds: string[]) {
  const status = useServerStatus(token);
  const missing = new Map<string, { serverId: string; name: string; removed: boolean; tools: string[] }>();
  if (status.loaded) {
    for (const id of toolIds) {
      const parts = id.split(":");
      if (parts.length < 3 || parts[0] !== "mcp" || status.isConnected(parts[1])) continue;
      const entry = missing.get(parts[1]) ?? { serverId: parts[1], name: status.name(parts[1]), removed: status.isGone(parts[1]), tools: [] };
      entry.tools.push(id);
      missing.set(parts[1], entry);
    }
  }
  return [...missing.values()];
}

/**
 * "Connect" that connects in place: opens the server's own connect dialog
 * (credentials, sign-in or QR) over whatever page it sits on. Safe inside
 * clickable cards and canvas nodes — its clicks never reach them.
 */
export function ConnectButton({
  serverId,
  token,
  serverName,
  className,
  onConnected,
}: {
  serverId: string;
  token: string;
  serverName?: string;
  className?: string;
  onConnected?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        title={serverName ? `Connect your ${serverName} account` : "Connect your account"}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className={cn(
          "nodrag nopan inline-flex shrink-0 items-center gap-1 rounded-md bg-sky-600 px-2 py-1 text-xs font-medium text-white hover:bg-sky-500 cursor-pointer",
          className,
        )}
      >
        <Link2 className="h-3 w-3" /> Connect{serverName ? ` ${serverName}` : ""}
      </button>
      {open && (
        // The dialog is portalled to <body>, but React still bubbles its
        // events through here — stop them before they reach a parent card/node.
        <div className="contents" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <ConnectServerDialog
            serverId={serverId}
            token={token}
            onClose={() => setOpen(false)}
            onConnected={() => {
              setOpen(false);
              onConnected?.();
            }}
          />
        </div>
      )}
    </>
  );
}
