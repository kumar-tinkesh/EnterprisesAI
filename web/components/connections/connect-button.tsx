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
  const catalog = useQuery({
    queryKey: ["catalog", token, ""],
    queryFn: () => vendorApi.getCatalog(token),
    enabled: !!token,
    staleTime: 30_000,
  });
  const ids = new Set((catalog.data?.servers ?? []).filter((s) => s.connected).map((s) => s.id));
  return (serverId: string, fallback = false) => (catalog.data ? ids.has(serverId) : fallback);
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
