"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, MessageSquare, Network, Pencil, Plus, Trash2 } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ChatPanel, type ChatTarget } from "@/components/builder/chat/chat-panel";
import { Avatar } from "@/components/builder/chat/chat-message";
import { AgentEditor } from "@/components/builder/agent-editor";
import { WorkflowEditor } from "@/components/builder/workflow-editor";
import { AgentWizardHost } from "@/components/builder/agent-wizard/agent-wizard";
import { builderApi } from "@/lib/builder/api";
import { useBuilderActions, type BuildMode, type BuildTarget } from "@/lib/builder/use-builder-actions";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const TAB_KEY = "projects.tab"; // kept so the saved tab survives the rename

/** ?chat=agent:<id> / ?chat=workflow:<id> — the chat open beside the list; &edit=1 — its editor in place of the list. */
function chatFromUrl(): ChatTarget | null {
  if (typeof window === "undefined") return null;
  const [kind, id] = (new URLSearchParams(window.location.search).get("chat") ?? "").split(":");
  return (kind === "agent" || kind === "workflow") && id ? { kind, id } : null;
}

function setChatUrl(target: ChatTarget | null, editing = false) {
  const url = new URL(window.location.href);
  if (target) url.searchParams.set("chat", `${target.kind}:${target.id}`);
  else url.searchParams.delete("chat");
  if (target && editing) url.searchParams.set("edit", "1");
  else url.searchParams.delete("edit");
  window.history.replaceState(null, "", url);
}

export default function ExecutionsPage() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const [tab, setTab] = useState<BuildMode>("agent");
  const [chat, setChat] = useState<ChatTarget | null>(null);
  // The chat's agent/workflow is open in the editor, in place of the list.
  const [editing, setEditing] = useState(false);
  const { createBlank, remove, error, setError } = useBuilderActions();

  useEffect(() => {
    const fromUrl = chatFromUrl();
    if (fromUrl) {
      setChat(fromUrl);
      setTab(fromUrl.kind);
      setEditing(new URLSearchParams(window.location.search).get("edit") === "1");
      return;
    }
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
  const openChat = (target: ChatTarget | null) => {
    setChat(target);
    setEditing(false);
    setChatUrl(target);
  };
  /** Open an agent/workflow in the editor (left) with its chat (right). */
  const openEditor = (target: BuildTarget) => {
    setChat(target);
    setTab(target.kind);
    setEditing(true);
    setChatUrl(target, true);
  };
  const closeEditor = () => {
    setEditing(false);
    setChatUrl(chat);
  };

  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });

  const items =
    tab === "agent"
      ? (agents.data ?? []).map((a) => ({ id: a.id, name: a.name, sub: a.goal, updated: a.updated_at, canManage: a.can_manage }))
      : (workflows.data ?? []).map((w) => ({ id: w.id, name: w.name, sub: `${w.node_count} steps${w.description ? ` · ${w.description}` : ""}`, updated: w.updated_at, canManage: w.can_manage }));
  const loading = tab === "agent" ? agents.isLoading : workflows.isLoading;

  const list = (
    <div className={cn("rounded-xl border border-zinc-200 bg-white", chat && "flex min-h-0 flex-1 flex-col")}>
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
        <span className="ml-auto hidden text-[11px] text-zinc-400 lg:inline">Click one to chat with it</span>
      </div>
      {loading ? (
        <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>
      ) : items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-zinc-400">
          Nothing here yet. Start one with New {tab}.
        </p>
      ) : (
        <ul className={cn("divide-y divide-zinc-100", chat && "min-h-0 flex-1 overflow-y-auto")}>
          {items.map((item) => {
            const active = chat?.kind === tab && chat.id === item.id;
            return (
              <li key={item.id} className={cn("group flex items-center gap-2 pr-3", active ? "bg-indigo-50/70" : "hover:bg-zinc-50")}>
                <button
                  type="button"
                  onClick={() => openChat({ kind: tab, id: item.id })}
                  aria-current={active ? "true" : undefined}
                  title={`Chat with ${item.name}`}
                  className="flex min-w-0 flex-1 items-center gap-3 py-3 pl-4 text-left cursor-pointer sm:pl-5"
                >
                  <Avatar name={item.name} size={34} />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate font-medium", active ? "text-indigo-700" : "text-zinc-900")}>{item.name}</span>
                    <span className="block truncate text-xs text-zinc-500">{item.sub}</span>
                  </span>
                  <span className={cn("hidden text-xs text-zinc-400", !chat && "sm:block")}>{new Date(item.updated).toLocaleDateString()}</span>
                  <MessageSquare className={cn("h-4 w-4 shrink-0", active ? "text-indigo-500" : "text-zinc-400 group-hover:text-indigo-400")} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => openEditor({ kind: tab, id: item.id })}
                  aria-label={`Edit ${item.name}`}
                  title="Edit"
                  className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer"
                >
                  <Pencil className="h-4 w-4" />
                </button>
                {item.canManage && (
                  <button
                    type="button"
                    aria-label={`Delete ${item.name}`}
                    title="Delete"
                    className="rounded-md p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600 cursor-pointer"
                    onClick={() => {
                      if (window.confirm(`Delete "${item.name}"? This can't be undone.`)) {
                        remove.mutate({ kind: tab, id: item.id });
                        if (active) openChat(null);
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );

  const actions = (
    <div className="flex items-center gap-2">
      <Button variant="outline" disabled={createBlank.isPending} onClick={() => createBlank.mutate(tab)} aria-label={`New blank ${tab}`}>
        {createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} <span className={cn(chat && "hidden xl:inline")}>New blank {tab}</span>
      </Button>
    </div>
  );

  // A saved wizard hands its agent over: open it in the editor here.
  const wizard = <AgentWizardHost onOpen={openEditor} />;

  // A chat is open: the list keeps the left half, the chat takes the right
  // (the whole screen on a phone, with a way back to the list). Editing swaps
  // the list for the editor, which takes the phone screen instead of the chat.
  if (chat) {
    return (
      <ProtectedDashboard path="/user" title="Executions" description="Run your agents and workflows, shared with your team." fullBleed>
        <div className="flex h-dvh overflow-hidden bg-zinc-950">
          {editing ? (
            <section className="flex min-w-0 flex-1 flex-col md:w-[58%] md:flex-none [&>div]:h-full" aria-label="Editor">
              {chat.kind === "workflow" ? (
                <WorkflowEditor key={chat.id} id={chat.id} onBack={closeEditor} onOpen={openEditor} onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })} />
              ) : (
                <AgentEditor key={chat.id} id={chat.id} onBack={closeEditor} onOpen={openEditor} />
              )}
            </section>
          ) : (
          <section className="hidden min-w-0 flex-col gap-3 p-4 md:flex md:w-2/5 lg:w-1/3 lg:p-6">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-lg font-bold text-zinc-900">Executions</h1>
              <div className="ml-auto">{actions}</div>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            {list}
          </section>
          )}
          <section className={cn("min-w-0 flex-1 flex-col border-zinc-200 shadow-xl md:flex md:border-l", editing ? "hidden" : "flex")} aria-label="Chat">
            <ChatPanel
              key={`${chat.kind}:${chat.id}`}
              target={chat}
              token={token}
              onClose={() => openChat(null)}
              onEdit={() => openEditor(chat)}
            />
          </section>
        </div>
        {wizard}
      </ProtectedDashboard>
    );
  }

  return (
    <ProtectedDashboard path="/user" title="Executions" description="Run your agents and workflows, shared with your team.">
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="ml-auto">{actions}</div>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4">{list}</div>
      {wizard}
    </ProtectedDashboard>
  );
}
