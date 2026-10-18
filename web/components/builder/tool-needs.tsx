"use client";

import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Clock, Plug } from "lucide-react";

import { ConnectButton } from "@/components/connections/connect-button";
import { ConnectServerDialog } from "@/components/connections/server-connect";
import { builderApi } from "@/lib/builder/api";
import type { ToolNeed, ToolNeedStatus } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/**
 * Where each of a step's tool needs stands for the signed-in user. Refreshed
 * when a server is connected anywhere (the connect dialog invalidates
 * "builder-tool-needs"), so a node picks up a system the moment it's connected.
 */
export function useToolNeedStatus(token: string, needs: ToolNeed[] | undefined) {
  const list = needs ?? [];
  return useQuery({
    queryKey: ["builder-tool-needs", token, JSON.stringify(list)],
    queryFn: () => builderApi.toolNeedsStatus(token, list),
    enabled: !!token && list.length > 0,
    staleTime: 15_000,
  });
}

const STATUS: Record<ToolNeedStatus["status"], { label: string; tone: string; Icon: typeof CheckCircle2 }> = {
  ready: { label: "connected", tone: "text-emerald-400", Icon: CheckCircle2 },
  not_connected: { label: "connect your account", tone: "text-sky-400", Icon: Plug },
  not_verified: { label: "added, waiting for admin to connect it", tone: "text-amber-400", Icon: Clock },
  missing: { label: "ask your admin to add it", tone: "text-zinc-500", Icon: CircleDashed },
};

/** One line per system: its state, its tools once ready, and Connect in place when it's the person's turn.
 *  ``onConnect``: inside a popover, let its owner open the dialog (after closing the popover, which
 *  would otherwise sit above it). */
export function NeedsList({
  token,
  statuses,
  light = false,
  onConnect,
}: {
  token: string;
  statuses: ToolNeedStatus[];
  light?: boolean;
  onConnect?: (s: ToolNeedStatus) => void;
}) {
  return (
    <ul className="space-y-1">
      {statuses.map((s) => {
        const st = STATUS[s.status];
        return (
          <li key={s.system} className={cn("rounded-md px-1.5 py-1", light ? "hover:bg-zinc-50" : "hover:bg-white/5")}>
            <div className="flex items-center gap-1.5">
              <st.Icon className={cn("h-3.5 w-3.5 shrink-0", st.tone)} />
              <span className={cn("min-w-0 flex-1 truncate text-[11.5px] font-medium", light ? "text-zinc-800" : "text-zinc-100")}>
                {s.system}
                {s.required && <span className="ml-1 text-[10px] font-normal text-amber-500">required</span>}
              </span>
              {s.status === "not_connected" && s.server_id && (onConnect ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onConnect(s);
                  }}
                  className="nodrag nopan inline-flex shrink-0 items-center gap-1 rounded-full bg-sky-600 px-2 py-0.5 text-[10.5px] font-medium text-white hover:bg-sky-500 cursor-pointer"
                >
                  <Plug className="h-3 w-3" /> Connect
                </button>
              ) : (
                <ConnectButton serverId={s.server_id} serverName={s.server_name ?? undefined} token={token} className="rounded-full px-2 py-0.5 text-[10.5px]" />
              ))}
            </div>
            <p className="pl-5 text-[10.5px] text-zinc-500" title={s.match.join(", ")}>
              {s.status === "ready" ? `${s.server_name} · ${s.tools.join(", ")}` : s.status === "missing" ? `${st.label} — ${s.match[0]}` : `${s.server_name} · ${st.label}`}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

/** How many systems are ready, and whether the step can't run yet (same rule as the backend's need_problems). */
export function needsSummary(statuses: ToolNeedStatus[]): { ready: number; total: number; blocked: boolean } {
  const ready = statuses.filter((s) => s.status === "ready").length;
  const requiredMissing = statuses.some((s) => s.required && s.status !== "ready");
  return { ready, total: statuses.length, blocked: requiredMissing || ready === 0 };
}

/** "2/4 systems" on an agent step; click for the list (in its own layer so the node card doesn't clip it). */
export function SystemsChip({ token, needs }: { token: string; needs: ToolNeed[] }) {
  const status = useToolNeedStatus(token, needs);
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);
  const ref = useRef<HTMLButtonElement>(null);
  if (needs.length === 0) return null;
  const statuses = status.data ?? [];
  const sum = needsSummary(statuses);
  return (
    <>
      <button
        ref={ref}
        type="button"
        title="Systems this step uses — their tools are added by themselves once connected"
        aria-expanded={!!at}
        onClick={(e) => {
          e.stopPropagation();
          const r = ref.current?.getBoundingClientRect();
          setAt(at || !r ? null : { top: r.bottom + 4, left: r.left });
        }}
        className={cn(
          "nodrag inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] cursor-pointer",
          !status.data
            ? "border-white/10 bg-white/5 text-zinc-400"
            : sum.blocked
              ? "border-amber-400/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
              : "border-emerald-400/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20",
        )}
      >
        <Plug className="h-3 w-3" /> {status.data ? `${sum.ready}/${sum.total}` : needs.length} system{needs.length === 1 ? "" : "s"}
      </button>
      {at &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[999]" onClick={() => setAt(null)} />
            <div style={at} className="fixed z-[1000] max-h-72 w-72 overflow-y-auto rounded-lg border border-white/10 bg-zinc-900 p-1.5 shadow-2xl">
              <p className="px-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Systems this step uses</p>
              {status.data ? (
                <NeedsList
                  token={token}
                  statuses={statuses}
                  onConnect={(s) => {
                    setAt(null);
                    setConnecting(s.server_id);
                  }}
                />
              ) : (
                <p className="px-1.5 py-1 text-[11px] text-zinc-500">Checking…</p>
              )}
              <p className="px-1.5 pt-1 text-[10px] text-zinc-500">
                {statuses.some((s) => s.required) ? "Runs once every required system is connected." : "Runs once at least one is connected; the others join as they're connected."}
              </p>
            </div>
          </>,
          document.body,
        )}
      {connecting && (
        // Portalled to <body>, but React still bubbles its events through the node — stop them here.
        <div className="contents" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />
        </div>
      )}
    </>
  );
}

/** In an agent's Tools settings: the systems it picks up by itself, and where each stands. */
export function NeedsSection({ token, needs }: { token: string; needs: ToolNeed[] }) {
  const status = useToolNeedStatus(token, needs);
  return (
    <div className="mt-3 rounded-lg border border-zinc-200 p-2">
      <p className="text-xs font-medium text-zinc-700">Systems it uses</p>
      <p className="mb-1.5 text-[11px] text-zinc-500">Their tools are added on every run once the system is connected — nothing to pick by hand.</p>
      {status.data ? <NeedsList token={token} statuses={status.data} light /> : <p className="text-[11px] text-zinc-400">Checking…</p>}
    </div>
  );
}
