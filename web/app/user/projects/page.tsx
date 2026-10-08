"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, Network, Plus, Trash2, Wand2 } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import { useBuilderActions, type BuildMode } from "@/lib/builder/use-builder-actions";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const TAB_KEY = "projects.tab";

export default function ProjectsPage() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const [tab, setTab] = useState<BuildMode>("agent");
  const { createBlank, remove, error, setError } = useBuilderActions();

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(TAB_KEY);
      if (saved === "agent" || saved === "workflow") setTab(saved);
    } catch {
      /* default */
    }
  }, []);
  const pickTab = (t: BuildMode) => {
    setTab(t);
    setError(null);
    try {
      window.localStorage.setItem(TAB_KEY, t);
    } catch {
      /* ignore */
    }
  };

  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });

  const items =
    tab === "agent"
      ? (agents.data ?? []).map((a) => ({ id: a.id, name: a.name, sub: a.goal, updated: a.updated_at, canManage: a.can_manage, href: `/user/builder/agents/${a.id}` }))
      : (workflows.data ?? []).map((w) => ({ id: w.id, name: w.name, sub: `${w.node_count} steps${w.description ? ` · ${w.description}` : ""}`, updated: w.updated_at, canManage: w.can_manage, href: `/user/builder/workflows/${w.id}` }));
  const loading = tab === "agent" ? agents.isLoading : workflows.isLoading;

  return (
    <ProtectedDashboard path="/user" title="Projects" description="Your agents and workflows, shared with your team.">
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <a href="/user" className="text-sm text-zinc-500 hover:text-zinc-800">← Back to workspace</a>
        <div className="ml-auto flex items-center gap-2">
          <a
            href="/user/agents"
            className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
          >
            <Wand2 className="h-4 w-4" /> Create with AI
          </a>
          <Button variant="outline" disabled={createBlank.isPending} onClick={() => createBlank.mutate(tab)}>
            {createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} New blank {tab}
          </Button>
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-4 rounded-xl border border-zinc-200 bg-white">
        <div className="flex items-center gap-1 border-b border-zinc-100 px-3 py-2" role="tablist" aria-label="Project items">
          {(["agent", "workflow"] as BuildMode[]).map((t) => {
            const count = t === "agent" ? agents.data?.length : workflows.data?.length;
            return (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                onClick={() => pickTab(t)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium cursor-pointer",
                  tab === t ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900",
                )}
              >
                {t === "agent" ? <Bot className="h-4 w-4" /> : <Network className="h-4 w-4" />}
                {t === "agent" ? "Agents" : "Workflows"}
                {count != null && <span className={cn("text-xs", tab === t ? "text-zinc-300" : "text-zinc-400")}>{count}</span>}
              </button>
            );
          })}
        </div>
        {loading ? (
          <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>
        ) : items.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-zinc-400">
            Nothing here yet. Describe one in the <a href="/user/agents" className="text-indigo-600 hover:underline">AI Compiler</a> or start blank.
          </p>
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
                      if (window.confirm(`Delete "${item.name}"? This can't be undone.`)) remove.mutate({ kind: tab, id: item.id });
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
