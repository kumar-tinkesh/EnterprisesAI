"use client";

import { useEffect, useState } from "react";
import { Bot, Network, Plus, Send, X } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { useBuilderActions, type BuildMode, type BuildTarget } from "@/lib/builder/use-builder-actions";
import { cn } from "@/lib/utils";

const MODE_KEY = "compiler.mode";
const MODES: { id: BuildMode; label: string; icon: typeof Bot; placeholder: string }[] = [
  { id: "agent", label: "Agent", icon: Bot, placeholder: "Describe an agent, e.g. an inbox assistant that reads my Gmail and drafts replies" },
  { id: "workflow", label: "Workflow", icon: Network, placeholder: "Describe a workflow, e.g. every morning summarize my unread Gmail and post it to Slack #team" },
];

export const barInput = "min-w-0 flex-1 bg-transparent px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none";
export const barButton = "flex h-9 shrink-0 items-center gap-1.5 rounded-xl px-4 text-xs font-semibold disabled:opacity-50 cursor-pointer";

/**
 * The one prompt bar at the bottom of the AI Compiler. Agent / Workflow tabs
 * pick what to build; with an agent or workflow of the picked kind open it
 * shows that one's own controls (``edit``) instead, and "New" switches back
 * to describing a new one. A new one opens in place (``onOpen``).
 */
export function BuildBar({
  current,
  edit,
  above,
  onOpen,
}: {
  /** The kind of what's open in the canvas, if anything. */
  current: BuildMode | null;
  /** The open one's controls (inputs + buttons), shown on its own tab. */
  edit?: React.ReactNode;
  /** Shown just above the bar (suggestion chips…), only alongside ``edit``. */
  above?: React.ReactNode;
  onOpen: (target: BuildTarget) => void;
}) {
  const builder = useBuilderActions({ open: onOpen });
  const [mode, setMode] = useState<BuildMode>(current ?? "agent");
  const [creating, setCreating] = useState(false);
  const [text, setText] = useState("");

  useEffect(() => {
    if (current) return;
    try {
      const saved = window.localStorage.getItem(MODE_KEY);
      if (saved === "agent" || saved === "workflow") setMode(saved);
    } catch {
      /* default */
    }
  }, [current]);

  const pick = (m: BuildMode) => {
    setMode(m);
    builder.setError(null);
    try {
      window.localStorage.setItem(MODE_KEY, m);
    } catch {
      /* not remembered */
    }
  };

  const pending = builder.createWithAi.isPending;
  const editing = !!edit && mode === current && !creating;

  return (
    <div className="shrink-0 border-t border-white/10 bg-zinc-950">
      {builder.error && <p className="px-4 pt-3 text-xs text-red-400">{builder.error}</p>}
      {pending && <p className="px-4 pt-3 text-xs text-zinc-400">Designing the {mode} and matching tools… this can take a few seconds.</p>}
      {editing && above && <div className="px-4 pt-3">{above}</div>}
      <div className="flex items-center gap-2 p-3">
        <div className="inline-flex shrink-0 rounded-xl border border-white/10 bg-white/5 p-1" role="tablist" aria-label="What to build">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="tab"
              aria-selected={mode === m.id}
              disabled={pending}
              onClick={() => pick(m.id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium cursor-pointer disabled:cursor-not-allowed",
                mode === m.id ? "bg-indigo-600 text-white" : "text-zinc-400 hover:text-zinc-100",
              )}
            >
              <m.icon className="h-3.5 w-3.5" />
              {m.label}
            </button>
          ))}
        </div>

        {editing ? (
          <>
            <div className="flex min-w-0 flex-1 items-center gap-2 rounded-2xl border border-white/15 bg-zinc-900/95 p-1.5">{edit}</div>
            <button
              type="button"
              onClick={() => setCreating(true)}
              title={`Describe a new ${mode}`}
              className={cn(barButton, "border border-white/10 text-zinc-200 hover:bg-zinc-800")}
            >
              <Plus className="h-3.5 w-3.5" /> New
            </button>
          </>
        ) : (
          <form
            className="flex min-w-0 flex-1 items-center gap-2 rounded-2xl border border-white/15 bg-zinc-900/95 p-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              const q = text.trim();
              if (q.length < 3 || pending) return;
              builder.createWithAi.mutate(
                { mode, description: q },
                {
                  onSuccess: () => {
                    setText("");
                    setCreating(false);
                  },
                },
              );
            }}
          >
            <input
              aria-label={`Describe a new ${mode}`}
              className={barInput}
              placeholder={MODES.find((m) => m.id === mode)!.placeholder}
              value={text}
              disabled={pending}
              onChange={(e) => setText(e.target.value)}
            />
            {creating && current && (
              <button
                type="button"
                aria-label="Cancel"
                onClick={() => setCreating(false)}
                className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            )}
            <button type="submit" disabled={pending || text.trim().length < 3} className={cn(barButton, "bg-indigo-600 text-white hover:bg-indigo-500")}>
              {pending ? <Spinner className="h-3.5 w-3.5" /> : <Send className="h-3.5 w-3.5" />} Create
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
