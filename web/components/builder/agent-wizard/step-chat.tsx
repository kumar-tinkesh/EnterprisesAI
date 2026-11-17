"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, MessageCircle, Plus, Trash2, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Textarea, Toggle } from "@/components/builder/fields";
import { Badge, Category, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";

const MAX_STARTERS = 4;

/**
 * What a person sees when they open a chat with the agent (a welcome line and
 * suggested first questions), and whether it keeps a long-term memory of each
 * person. (What it remembers about *you* is ``MyMemories``: yours to manage
 * even on a teammate's agent, so it lives outside the owner's settings.)
 */
export function ChatStep({ draft, update }: StepProps) {
  const config = draft.config;
  const chat = config.chat ?? {};
  const starters = chat.starters ?? [];
  const memory = { enabled: false, max_items: 50, ...(config.memory ?? {}) };
  const [next, setNext] = useState("");

  const setChat = (patch: Partial<NonNullable<typeof config.chat>>) => update({ ...draft, config: { ...config, chat: { ...chat, ...patch } } });
  const setMemory = (patch: Partial<typeof memory>) => update({ ...draft, config: { ...config, memory: { ...memory, ...patch } } });
  const addStarter = () => {
    const text = next.trim();
    if (!text || starters.includes(text) || starters.length >= MAX_STARTERS) return;
    setChat({ starters: [...starters, text] });
    setNext("");
  };

  return (
    <div className="space-y-3">
      <Category icon={MessageCircle} tone="sky" title="Welcome and starters" hint="Shown on an empty chat, so people know what to ask." badge={starters.length ? <Badge tone="sky">{starters.length} starters</Badge> : null}>
        <Field label="Welcome message" hint="One or two lines. Empty = its goal is shown instead.">
          <Textarea rows={2} maxLength={500} value={chat.welcome ?? ""} placeholder={`Hi! I'm ${draft.name || "your agent"}. Ask me about…`} onChange={(e) => setChat({ welcome: e.target.value })} />
        </Field>
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-zinc-700">Suggested questions <span className="font-normal text-zinc-400">({starters.length}/{MAX_STARTERS})</span></p>
          {starters.length > 0 && (
            <ul className="space-y-1">
              {starters.map((s) => (
                <li key={s} className="flex items-center gap-2 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs text-zinc-700">
                  <span className="min-w-0 flex-1 break-words">{s}</span>
                  <button type="button" aria-label={`Remove "${s}"`} onClick={() => setChat({ starters: starters.filter((x) => x !== s) })} className="shrink-0 text-zinc-400 hover:text-red-600 cursor-pointer">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {starters.length < MAX_STARTERS && (
            <div className="flex gap-2">
              <Input
                className="h-8 text-xs"
                maxLength={200}
                value={next}
                placeholder="e.g. What's the status of my last order?"
                onChange={(e) => setNext(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addStarter();
                  }
                }}
              />
              <button type="button" onClick={addStarter} disabled={!next.trim()} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 cursor-pointer">
                <Plus className="h-3.5 w-3.5" /> Add
              </button>
            </div>
          )}
          {starters.length === 0 && <p className="text-xs text-zinc-400">None yet: the chat shows general questions instead.</p>}
        </div>
        <Toggle
          checked={chat.answer_general ?? true}
          onChange={(answer_general) => setChat({ answer_general })}
          label="Answer greetings and general questions too, then say what it can help with"
        />
      </Category>

      <Category icon={Brain} tone="violet" title="Long-term memory" hint="It saves facts about each person (preferences, their project) and knows them in later chats." badge={<Badge tone={memory.enabled ? "violet" : "zinc"}>{memory.enabled ? "On" : "Off"}</Badge>}>
        <Toggle checked={memory.enabled} onChange={(enabled) => setMemory({ enabled })} label="Remember things about the people it works for" />
        {memory.enabled && (
          <Field label="Most facts kept per person" hint="When it's full, the oldest are forgotten first.">
            <Input className="h-8 w-28 text-xs" type="number" min={5} max={200} value={memory.max_items} onChange={(e) => setMemory({ max_items: Math.max(5, Math.min(200, Number(e.target.value) || 50)) })} />
          </Field>
        )}
        <p className="rounded-lg bg-zinc-50 p-2.5 text-xs leading-relaxed text-zinc-500">
          Each person&apos;s memories are private to them, like their chats. Runs through a published key or a webhook never read or save them.
        </p>
      </Category>
    </div>
  );
}

/** What the agent remembers about the signed-in person: look, add, forget. */
export function MyMemories({ agentId, token }: { agentId: string; token: string }) {
  const queryClient = useQueryClient();
  const key = ["builder-memories", agentId];
  const memories = useQuery({ queryKey: key, queryFn: () => builderApi.listMemories(token, agentId), enabled: !!token });
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });

  const add = useMutation({
    mutationFn: () => builderApi.addMemory(token, agentId, text.trim()),
    onSuccess: () => {
      setText("");
      setError(null);
      void refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Couldn't save that."),
  });
  const forget = useMutation({ mutationFn: (id: string) => builderApi.forgetMemory(token, agentId, id), onSuccess: () => void refresh() });
  const forgetAll = useMutation({ mutationFn: () => builderApi.forgetAllMemories(token, agentId), onSuccess: () => void refresh() });
  const list = memories.data ?? [];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-zinc-700">What it remembers about you</p>
        {list.length > 0 && (
          <button
            type="button"
            disabled={forgetAll.isPending}
            onClick={() => window.confirm("Forget everything it remembers about you?") && forgetAll.mutate()}
            className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50 cursor-pointer"
          >
            Forget all
          </button>
        )}
      </div>
      {memories.isLoading ? (
        <div className="flex justify-center py-2"><Spinner className="h-4 w-4 text-zinc-400" /></div>
      ) : list.length === 0 ? (
        <p className="text-xs text-zinc-400">Nothing yet. It saves facts as you chat, or add one yourself.</p>
      ) : (
        <ul className="max-h-56 space-y-1 overflow-y-auto">
          {list.map((m) => (
            <li key={m.id} className="group flex items-start gap-2 rounded-lg bg-violet-50/60 px-2.5 py-1.5 text-xs text-zinc-700">
              <span className="min-w-0 flex-1 break-words">{m.content}</span>
              <span className="shrink-0 text-xs text-zinc-400">{m.source_run_id ? "learned" : "added"}</span>
              <button type="button" aria-label="Forget this" onClick={() => forget.mutate(m.id)} className="shrink-0 text-zinc-400 hover:text-red-600 cursor-pointer">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) add.mutate();
        }}
      >
        <Input className="h-8 text-xs" maxLength={500} value={text} placeholder="e.g. I manage the Pune office" onChange={(e) => setText(e.target.value)} />
        <button type="submit" disabled={!text.trim() || add.isPending} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 cursor-pointer">
          {add.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />} Remember
        </button>
      </form>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
