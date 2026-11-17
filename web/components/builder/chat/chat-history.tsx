"use client";

import { useEffect, useRef, useState } from "react";
import { Check, History, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { ago } from "@/lib/builder/chat";
import type { Conversation } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** The chat list: open, rename or delete one, or start a new chat. */
export function ChatHistory({
  chats,
  loading,
  currentId,
  onOpen,
  onNew,
  onRename,
  onDelete,
}: {
  chats: Conversation[];
  loading: boolean;
  currentId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<unknown>;
  /** Rejects with the reason when it can't be deleted. */
  onDelete: (id: string) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

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

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setError(null);
        }}
        aria-expanded={open}
        aria-label="Chat history"
        title="Chat history"
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm cursor-pointer",
          open ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900",
        )}
      >
        <History className="h-4 w-4" />
        <span className="hidden sm:inline">History</span>
        {chats.length > 0 && <span className="text-xs tabular-nums text-zinc-500">{chats.length}</span>}
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-30 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-zinc-200 bg-[var(--surface-raised)] shadow-xl">
          <div className="flex items-center justify-between border-b border-zinc-100 px-3 py-2">
            <p className="text-xs font-semibold text-zinc-900">Your chats</p>
            <button
              type="button"
              onClick={() => {
                onNew();
                setOpen(false);
              }}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"
            >
              <Plus className="h-3 w-3" /> New chat
            </button>
          </div>
          {error && <p className="border-b border-zinc-100 px-3 py-2 text-xs text-red-600" role="alert">{error}</p>}
          <ul className="max-h-80 overflow-y-auto p-1.5">
            {loading ? (
              <li className="flex justify-center py-6"><Spinner className="h-4 w-4 text-zinc-400" /></li>
            ) : chats.length === 0 ? (
              <li className="px-2 py-6 text-center text-xs text-zinc-400">No chats yet. Your first message starts one.</li>
            ) : (
              chats.map((c) => (
                <li key={c.id} className={cn("group flex items-center gap-1 rounded-lg", c.id === currentId ? "bg-indigo-50" : "hover:bg-zinc-50")}>
                  {editing?.id === c.id ? (
                    <form
                      className="flex min-w-0 flex-1 items-center gap-1 p-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const title = editing.title.trim();
                        if (title) void act(c.id, () => onRename(c.id, title)).then(() => setEditing(null));
                      }}
                    >
                      <input
                        autoFocus
                        aria-label="Chat name"
                        value={editing.title}
                        maxLength={200}
                        onChange={(e) => setEditing({ id: c.id, title: e.target.value })}
                        onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), setEditing(null))}
                        className="h-7 min-w-0 flex-1 rounded-md border border-zinc-300 px-2 text-xs outline-none focus:border-indigo-400"
                      />
                      <button type="submit" aria-label="Save name" className="rounded-md p-1 text-emerald-600 hover:bg-emerald-50 cursor-pointer"><Check className="h-3.5 w-3.5" /></button>
                      <button type="button" aria-label="Cancel" onClick={() => setEditing(null)} className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 cursor-pointer"><X className="h-3.5 w-3.5" /></button>
                    </form>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          onOpen(c.id);
                          setOpen(false);
                        }}
                        className="flex min-w-0 flex-1 items-start gap-2 px-2 py-2 text-left cursor-pointer"
                      >
                        <MessageSquare className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", c.id === currentId ? "text-indigo-500" : "text-zinc-400")} />
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-medium text-zinc-900">{c.title}</span>
                          <span className="text-xs text-zinc-400">
                            {c.turn_count} message{c.turn_count === 1 ? "" : "s"} · {ago(c.last_message_at ?? c.created_at)}
                          </span>
                        </span>
                      </button>
                      <span className="flex shrink-0 items-center pr-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                        <button
                          type="button"
                          aria-label={`Rename ${c.title}`}
                          title="Rename"
                          onClick={() => setEditing({ id: c.id, title: c.title })}
                          className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete ${c.title}`}
                          title="Delete"
                          disabled={busy === c.id}
                          onClick={() => {
                            if (window.confirm(`Delete "${c.title}"? Its messages and run history are removed. This can't be undone.`)) {
                              void act(c.id, () => onDelete(c.id));
                            }
                          }}
                          className="rounded-md p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 cursor-pointer"
                        >
                          {busy === c.id ? <Spinner className="h-3 w-3" /> : <Trash2 className="h-3 w-3" />}
                        </button>
                      </span>
                    </>
                  )}
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
