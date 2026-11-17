"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, Users, X } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import type { Agent } from "@/lib/builder/types";

/** Save an agent file the browser can download. */
/** ``team``: the agents it hands work to go in the same file, so the whole team imports in one go. */
export async function downloadAgentFile(token: string, agent: Pick<Agent, "id" | "name">, team = false): Promise<void> {
  const file = await builderApi.exportAgent(token, agent.id, team);
  const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const slug = agent.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "agent";
  a.download = `${slug}${file.agents?.length ? "-team" : ""}.agent.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Export an agent as a file another workspace can import (the other half is "Import an agent file" on the canvas). */
export function ExportPanel({ agent, token, onClose }: { agent: Agent; token: string; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const teamSize = agent.config?.sub_agent_ids?.length ?? 0;
  const exporting = useMutation({
    mutationFn: (team: boolean) => downloadAgentFile(token, agent, team),
    onError: (err) => setError(err instanceof Error ? err.message : "Couldn't export it."),
  });

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3">
        <Download className="h-4 w-4 text-indigo-600" />
        <h2 className="flex-1 text-sm font-semibold text-zinc-900">Export</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {error && <p className="rounded-lg bg-red-50 p-2.5 text-xs text-red-700">{error}</p>}
        <p className="text-xs text-zinc-500">
          A JSON file with its instructions and settings. Tools are saved by server and tool name, so they reconnect in another workspace that has the same servers; anything missing is reported on import.
        </p>
        {teamSize > 0 && (
          <div className="space-y-1.5 rounded-lg border border-indigo-200 bg-indigo-50/50 p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-zinc-900"><Users className="h-3.5 w-3.5 text-indigo-600" /> With its team</p>
            <p className="text-xs text-zinc-500">
              This agent and the {teamSize} agent{teamSize === 1 ? "" : "s"} it hands work to, in one file. Importing it creates the whole team at once, already linked.
            </p>
            <button
              type="button"
              onClick={() => exporting.mutate(true)}
              disabled={exporting.isPending}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-indigo-600 px-3 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 cursor-pointer"
            >
              {exporting.isPending && exporting.variables ? <Spinner className="h-3.5 w-3.5" /> : <Download className="h-3.5 w-3.5" />} Download team (.agent.json)
            </button>
          </div>
        )}
        <button
          type="button"
          onClick={() => exporting.mutate(false)}
          disabled={exporting.isPending}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-zinc-200 px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 cursor-pointer"
        >
          {exporting.isPending && !exporting.variables ? <Spinner className="h-3.5 w-3.5" /> : <Download className="h-3.5 w-3.5" />} Download {teamSize > 0 ? "this agent only" : ".agent.json"}
        </button>
      </div>
    </div>
  );
}
