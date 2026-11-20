"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, MessageSquare, PanelLeftClose, Pencil, Plus, Trash2, X } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { ago } from "@/lib/builder/chat";
import type { Conversation } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

function groupChatsByDate(chats: Conversation[]) {
  const now = Date.now();
  const ONE_DAY = 24 * 60 * 60 * 1000;

  const groups: { label: string; chats: Conversation[] }[] = [
    { label: "Today", chats: [] },
    { label: "Yesterday", chats: [] },
    { label: "Previous 7 days", chats: [] },
    { label: "Older", chats: [] },
  ];

  for (const c of chats) {
    const time = new Date(c.last_message_at ?? c.created_at).getTime();
    const diff = now - time;
    if (diff < ONE_DAY) groups[0].chats.push(c);
    else if (diff < 2 * ONE_DAY) groups[1].chats.push(c);
    else if (diff < 7 * ONE_DAY) groups[2].chats.push(c);
    else groups[3].chats.push(c);
  }

  return groups.filter((g) => g.chats.length > 0);
}

export function ChatSessionSidebar({
  chats,
  loading,
  currentId,
  open,
  onToggle,
  onOpen,
  onNew,
  onRename,
  onDelete,
}: {
  chats: Conversation[];
  loading: boolean;
  currentId: string | null;
  open: boolean;
  onToggle: () => void;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<unknown>;
  onDelete: (id: string) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(id);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      setBusy(null);
    }
  };

  const grouped = useMemo(() => groupChatsByDate(chats), [chats]);

  if (!open) return null;

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-white/10 bg-[var(--surface)] text-xs transition-all">
      {/* Sidebar Header */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/10 px-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-zinc-200">Chat Sessions</span>
          {chats.length > 0 && (
            <span className="rounded-full bg-white/[0.08] px-2 py-0.5 text-[10px] font-medium text-zinc-400 tabular-nums">
              {chats.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onToggle}
          title="Collapse session sidebar"
          aria-label="Collapse session sidebar"
          className="rounded-md p-1.5 text-zinc-400 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* New Chat Button */}
      <div className="p-3 border-b border-white/5">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-zinc-200 hover:border-white/20 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors shadow-xs"
        >
          <Plus className="h-3.5 w-3.5 text-indigo-400" />
          <span>New Chat</span>
        </button>
      </div>

      {error && (
        <p className="border-b border-white/10 bg-red-500/10 px-3 py-2 text-xs text-red-400" role="alert">
          {error}
        </p>
      )}

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-2 py-3 [scrollbar-width:thin]">
        {loading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-4 w-4 text-zinc-400" />
          </div>
        ) : chats.length === 0 ? (
          <div className="px-3 py-8 text-center text-zinc-500">
            <MessageSquare className="mx-auto mb-2 h-6 w-6 opacity-40" />
            <p>No chat history yet.</p>
            <p className="mt-1 text-[11px] text-zinc-600">Send a message to start a session.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {grouped.map((group) => (
              <div key={group.label} className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {group.chats.map((c) => {
                    const isActive = c.id === currentId;
                    return (
                      <li
                        key={c.id}
                        className={cn(
                          "group relative flex items-center rounded-lg transition-colors",
                          isActive
                            ? "bg-indigo-500/15 text-indigo-200 border border-indigo-500/30"
                            : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200"
                        )}
                      >
                        {editing?.id === c.id ? (
                          <form
                            className="flex min-w-0 flex-1 items-center gap-1 p-1"
                            onSubmit={(e) => {
                              e.preventDefault();
                              const title = editing.title.trim();
                              if (title) {
                                void act(c.id, () => onRename(c.id, title)).then(() => setEditing(null));
                              }
                            }}
                          >
                            <input
                              autoFocus
                              aria-label="Chat title"
                              value={editing.title}
                              maxLength={200}
                              onChange={(e) => setEditing({ id: c.id, title: e.target.value })}
                              onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), setEditing(null))}
                              className="h-6 min-w-0 flex-1 rounded border border-indigo-500/50 bg-black/40 px-1.5 text-xs text-white outline-none"
                            />
                            <button
                              type="submit"
                              aria-label="Save name"
                              className="rounded p-1 text-emerald-400 hover:bg-white/10 cursor-pointer"
                            >
                              <Check className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              aria-label="Cancel"
                              onClick={() => setEditing(null)}
                              className="rounded p-1 text-zinc-400 hover:bg-white/10 cursor-pointer"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </form>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => onOpen(c.id)}
                              className="flex min-w-0 flex-1 items-start gap-2 px-2.5 py-2 text-left cursor-pointer"
                            >
                              <MessageSquare
                                className={cn(
                                  "mt-0.5 h-3.5 w-3.5 shrink-0",
                                  isActive ? "text-indigo-400" : "text-zinc-500 group-hover:text-zinc-400"
                                )}
                              />
                              <div className="min-w-0 flex-1">
                                <span className={cn("block truncate text-xs font-medium", isActive ? "text-indigo-100" : "text-zinc-300")}>
                                  {c.title}
                                </span>
                                <span className="block text-[10px] text-zinc-500">
                                  {c.turn_count} msg{c.turn_count === 1 ? "" : "s"} · {ago(c.last_message_at ?? c.created_at)}
                                </span>
                              </div>
                            </button>
                            <div className="flex shrink-0 items-center pr-1.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                              <button
                                type="button"
                                aria-label={`Rename ${c.title}`}
                                title="Rename"
                                onClick={() => setEditing({ id: c.id, title: c.title })}
                                className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-zinc-200 cursor-pointer"
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                aria-label={`Delete ${c.title}`}
                                title="Delete"
                                disabled={busy === c.id}
                                onClick={() => {
                                  if (
                                    window.confirm(
                                      `Delete "${c.title}"? Its messages and run history are removed.`
                                    )
                                  ) {
                                    void act(c.id, () => onDelete(c.id));
                                  }
                                }}
                                className="rounded p-1 text-zinc-400 hover:bg-red-500/20 hover:text-red-400 disabled:opacity-50 cursor-pointer"
                              >
                                {busy === c.id ? <Spinner className="h-3 w-3" /> : <Trash2 className="h-3 w-3" />}
                              </button>
                            </div>
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
