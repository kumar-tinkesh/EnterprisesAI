"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Upload } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import type { Agent, AgentFile } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/**
 * Import an agent from a file exported elsewhere (Share → Export). Tools are
 * matched by server and tool name; what this workspace doesn't have is listed
 * before the new agent opens.
 */
export function ImportAgentButton({ token, onImported, className }: { token: string; onImported: (agent: Agent) => void; className?: string }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ agent: Agent; skipped: string[] } | null>(null);

  const read = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      let parsed: AgentFile;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error("That file isn't valid JSON.");
      }
      const out = await builderApi.importAgent(token, parsed);
      void queryClient.invalidateQueries({ queryKey: ["builder-agents"] });
      if (out.skipped.length) setResult(out);
      else onImported(out.agent);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't import it.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(e) => {
          void read(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={busy}
        className={cn("inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium disabled:opacity-60 cursor-pointer", className)}
      >
        {busy ? <Spinner className="h-3.5 w-3.5" /> : <Upload className="h-3.5 w-3.5" />} Import an agent file
      </button>
      {error && <p className="mt-1.5 text-xs text-red-500" role="alert">{error}</p>}
      {result && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 p-4" role="dialog" aria-modal="true" aria-label="Imported with gaps">
          <div className="w-full max-w-md space-y-3 rounded-xl bg-white p-5 text-left shadow-xl">
            <p className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
              <AlertTriangle className="h-4 w-4 text-amber-500" /> Imported &ldquo;{result.agent.name}&rdquo;, with gaps
            </p>
            <p className="text-xs text-zinc-500">These weren&apos;t found here, so the agent was created without them. Add replacements in its settings.</p>
            <ul className="max-h-48 space-y-1 overflow-y-auto">
              {result.skipped.map((s, i) => <li key={i} className="rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900">{s}</li>)}
            </ul>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => {
                  const agent = result.agent;
                  setResult(null);
                  onImported(agent);
                }}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 cursor-pointer"
              >
                Open it
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
