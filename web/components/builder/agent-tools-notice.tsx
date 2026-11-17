"use client";

import { Bot, CheckCircle2 } from "lucide-react";

import { ConnectButton, useConnectedServers } from "@/components/connections/connect-button";
import { appsOf } from "@/lib/builder/agent-wizard";
import type { AgentToolReport } from "@/lib/builder/types";

/**
 * After an AI edit: each agent it added or rewrote, the apps its tools come from, and Connect right
 * there for any that isn't connected yet — so the person can finish setting it up without hunting
 * through Configure. ``onOpen`` opens the step's Configure panel (to add more, or when nothing fit).
 */
export function AgentToolsNotice({
  token,
  reports,
  onOpen,
}: {
  token: string;
  reports: [string, AgentToolReport][];
  onOpen: (nodeId: string) => void;
}) {
  const isConnected = useConnectedServers(token);
  if (reports.length === 0) return null;
  return (
    <ul className="mt-1.5 space-y-1">
      {reports.map(([nodeId, r]) => {
        const apps = appsOf(r.tools);
        const more = appsOf(r.related).filter((a) => !apps.some((p) => p.serverId === a.serverId));
        return (
          <li key={nodeId} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Bot className="h-3.5 w-3.5 shrink-0" />
            <span className="font-semibold">{r.agent}</span>
            {apps.length > 0 ? (
              apps.map((a) => (
                <span key={a.serverId} className="inline-flex items-center gap-1">
                  → {a.serverName} ({a.count} tool{a.count === 1 ? "" : "s"})
                  {isConnected(a.serverId, a.connected) ? (
                    <CheckCircle2 className="h-3 w-3 text-emerald-600" aria-label="Connected" />
                  ) : (
                    <ConnectButton serverId={a.serverId} token={token} className="px-2 py-0.5 text-xs" />
                  )}
                </span>
              ))
            ) : (
              <span>{r.need ? "→ no app found for this yet" : "→ no tools (works from what it's given)"}</span>
            )}
            {(more.length > 0 || (r.need && apps.length === 0)) && (
              <button type="button" onClick={() => onOpen(nodeId)} className="font-medium underline cursor-pointer">
                {more.length > 0 ? `Also: ${more.map((a) => a.serverName).join(", ")} — Configure` : "Open Configure"}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
