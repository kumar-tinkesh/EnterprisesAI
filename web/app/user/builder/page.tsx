"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Bot, Network, Plus, Sparkles, Trash2, Wand2 } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/builder/fields";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { draftKey } from "@/lib/builder/graph";
import type { Problem } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

type Mode = "agent" | "workflow";
const MODE_KEY = "builder.mode";

const EXAMPLES: Record<Mode, string[]> = {
  agent: [
    "A support agent that answers from our policy documents and opens a Jira ticket when it can't help",
    "An inbox assistant that reads my Gmail and drafts replies",
  ],
  workflow: [
    "Every morning summarize my unread Gmail and post the summary to Slack #team",
    "When a lead comes in, look them up in HubSpot, draft an intro email, and ask me to approve before sending",
  ],
};

export default function BuilderStudio() {
  const router = useRouter();
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("workflow");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(MODE_KEY);
      if (saved === "agent" || saved === "workflow") setMode(saved);
    } catch {
      /* default */
    }
  }, []);
  const pickMode = (m: Mode) => {
    setMode(m);
    setError(null);
    try {
      window.localStorage.setItem(MODE_KEY, m);
    } catch {
      /* ignore */
    }
  };

  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });

  const fail = (err: unknown) => {
    const problems = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
    setError(problems.length ? problems.map((p) => p.message).join(" ") : err instanceof Error ? err.message : "Something went wrong.");
  };

  const createWithAi = useMutation({
    mutationFn: async () => {
      setError(null);
      if (mode === "workflow") {
        const draft = await builderApi.draftWorkflow(token, description);
        const wf = await builderApi.createWorkflow(token, { name: draft.name, description });
        window.sessionStorage.setItem(draftKey(wf.id), JSON.stringify(draft));
        return `/user/builder/workflows/${wf.id}`;
      }
      const draft = await builderApi.draftAgent(token, description);
      const agent = await builderApi.createAgent(token, {
        name: draft.name, role: draft.role, goal: draft.goal, instructions: draft.instructions, config: draft.config,
      });
      const connect = draft.needs_connection.map((s) => s.server_name);
      window.sessionStorage.setItem(
        `builder.agent-notice.${agent.id}`,
        JSON.stringify({
          tone: connect.length ? "warn" : "ok",
          text: "Created by AI — check it, then test it in the playground.",
          detail: connect.length ? [`Connect before running: ${connect.join(", ")}`] : undefined,
        }),
      );
      return `/user/builder/agents/${agent.id}`;
    },
    onSuccess: (href) => router.push(href),
    onError: fail,
  });

  const createBlank = useMutation({
    mutationFn: async () => {
      setError(null);
      if (mode === "workflow") {
        const wf = await builderApi.createWorkflow(token, {
          name: "New workflow",
          nodes: [
            { id: "in", type: "input", position: { x: 0, y: 0 } },
            { id: "out", type: "output", position: { x: 600, y: 0 } },
          ],
          edges: [{ id: "e1", source: "in", target: "out" }],
        });
        return `/user/builder/workflows/${wf.id}`;
      }
      const agent = await builderApi.createAgent(token, { name: "New agent", role: "Assistant", goal: "Describe what this agent does" });
      return `/user/builder/agents/${agent.id}`;
    },
    onSuccess: (href) => router.push(href),
    onError: fail,
  });

  const remove = useMutation({
    mutationFn: ({ kind, id }: { kind: Mode; id: string }) => (kind === "agent" ? builderApi.deleteAgent(token, id) : builderApi.deleteWorkflow(token, id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["builder-agents"] });
      void queryClient.invalidateQueries({ queryKey: ["builder-workflows"] });
    },
    onError: fail,
  });

  const items =
    mode === "agent"
      ? (agents.data ?? []).map((a) => ({ id: a.id, name: a.name, sub: a.goal, updated: a.updated_at, canManage: a.can_manage, href: `/user/builder/agents/${a.id}` }))
      : (workflows.data ?? []).map((w) => ({ id: w.id, name: w.name, sub: `${w.node_count} steps${w.description ? ` · ${w.description}` : ""}`, updated: w.updated_at, canManage: w.can_manage, href: `/user/builder/workflows/${w.id}` }));
  const loading = mode === "agent" ? agents.isLoading : workflows.isLoading;
  const busy = createWithAi.isPending || createBlank.isPending;

  return (
    <ProtectedDashboard path="/user" title="Builder Studio" description="Build agents and workflows — describe them, or draw them on the canvas.">
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-1" role="tablist" aria-label="What to build">
          {(["agent", "workflow"] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => pickMode(m)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium cursor-pointer",
                mode === m ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900",
              )}
            >
              {m === "agent" ? <Bot className="h-4 w-4" /> : <Network className="h-4 w-4" />}
              {m === "agent" ? "Agent builder" : "Workflow builder"}
            </button>
          ))}
        </div>
        <a href="/user/agents" className="text-sm text-zinc-500 hover:text-zinc-900"><Wand2 className="mr-1 inline h-4 w-4" />AI Compiler</a>
        <a href="/user/knowledge" className="text-sm text-zinc-500 hover:text-zinc-900"><BookOpen className="mr-1 inline h-4 w-4" />Knowledge</a>
      </div>

      <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-5">
        <h2 className="flex items-center gap-2 font-semibold text-zinc-900">
          <Sparkles className="h-4 w-4 text-indigo-500" />
          {mode === "agent" ? "Describe the agent you want" : "Describe the process to automate"}
        </h2>
        <p className="mt-1 text-sm text-zinc-500">
          The AI drafts it and picks tools from your connected systems with semantic search. You review everything before it runs.
        </p>
        <Textarea
          rows={3}
          className="mt-3"
          value={description}
          placeholder={EXAMPLES[mode][0]}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES[mode].map((ex) => (
            <button key={ex} type="button" onClick={() => setDescription(ex)} className="rounded-full border border-zinc-200 px-2.5 py-1 text-xs text-zinc-600 hover:border-indigo-300 cursor-pointer">
              {ex.length > 60 ? `${ex.slice(0, 60)}…` : ex}
            </button>
          ))}
        </div>
        <div className="mt-3 flex gap-2">
          <Button disabled={busy || description.trim().length < 3} onClick={() => createWithAi.mutate()}>
            {createWithAi.isPending ? <Spinner className="h-4 w-4" /> : <Sparkles />} Create with AI
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => createBlank.mutate()}>
            {createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} Start blank
          </Button>
        </div>
        {createWithAi.isPending && <p className="mt-2 text-xs text-zinc-500">Designing it and matching tools… this can take a few seconds.</p>}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      <div className="mt-6 rounded-xl border border-zinc-200 bg-white">
        <h2 className="border-b border-zinc-100 px-5 py-3 font-semibold text-zinc-900">
          {mode === "agent" ? "Agents" : "Workflows"} <span className="text-sm font-normal text-zinc-400">shared with your team</span>
        </h2>
        {loading ? (
          <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>
        ) : items.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-zinc-400">Nothing here yet — create one above.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-5 py-3">
                <a href={item.href} className="min-w-0 flex-1">
                  <p className="truncate font-medium text-zinc-900 hover:text-indigo-700">{item.name}</p>
                  <p className="truncate text-xs text-zinc-500">{item.sub}</p>
                </a>
                <span className="hidden text-xs text-zinc-400 sm:block">{new Date(item.updated).toLocaleDateString()}</span>
                {item.canManage && (
                  <button
                    type="button"
                    aria-label={`Delete ${item.name}`}
                    className="text-zinc-300 hover:text-red-600 cursor-pointer"
                    onClick={() => {
                      if (window.confirm(`Delete "${item.name}"? This can't be undone.`)) remove.mutate({ kind: mode, id: item.id });
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </ProtectedDashboard>
  );
}
