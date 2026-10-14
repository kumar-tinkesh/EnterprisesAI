"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Pause, Play, Plus, Trash2, Webhook as WebhookIcon } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Section, Textarea } from "@/components/builder/fields";
import { builderApi } from "@/lib/builder/api";
import type { Webhook } from "@/lib/builder/types";

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-white p-1.5">
      <code className="min-w-0 flex-1 break-all text-[11px] text-zinc-800">{value}</code>
      <button
        type="button"
        aria-label="Copy URL"
        onClick={() => {
          void navigator.clipboard?.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="shrink-0 rounded p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

/**
 * An agent's webhooks: a secret URL that runs it on whatever is posted there
 * (a form, Zapier, a Slack command, a mail service's inbound route). Each runs
 * as the person who made it, so only they see it here.
 */
export function AgentWebhooks({ agentId, token }: { agentId: string; token: string }) {
  const queryClient = useQueryClient();
  const key = ["builder-webhooks", agentId];
  const list = useQuery({ queryKey: key, queryFn: () => builderApi.listWebhooks(token, agentId), enabled: !!token });
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ name: "", instruction: "", requests_per_minute: 10 });
  const [created, setCreated] = useState<{ id: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong.");

  const create = useMutation({
    mutationFn: () => builderApi.createWebhook(token, agentId, { ...draft, name: draft.name.trim() || "Webhook" }),
    onSuccess: (hook) => {
      setCreated({ id: hook.id, url: hook.url });
      setAdding(false);
      setDraft({ name: "", instruction: "", requests_per_minute: 10 });
      setError(null);
      void refresh();
    },
    onError: fail,
  });
  const toggle = useMutation({ mutationFn: (h: Webhook) => builderApi.updateWebhook(token, h.id, { enabled: !h.enabled }), onSuccess: () => void refresh(), onError: fail });
  const remove = useMutation({ mutationFn: (h: Webhook) => builderApi.deleteWebhook(token, h.id), onSuccess: () => void refresh(), onError: fail });

  return (
    <Section
      title={`Webhooks (${list.data?.length ?? 0})`}
      action={
        !adding && (
          <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer">
            <Plus className="h-3 w-3" /> Add
          </button>
        )
      }
    >
      {error && <p className="text-xs text-red-600">{error}</p>}
      {list.isLoading && <div className="flex justify-center py-2"><Spinner className="h-4 w-4 text-zinc-400" /></div>}
      {(list.data ?? []).length === 0 && !adding && !list.isLoading && (
        <p className="text-xs text-zinc-500">None yet. A webhook gives you a URL; anything posted to it (JSON, a form, plain text) is what the agent works on.</p>
      )}
      {(list.data ?? []).map((h) => (
        <div key={h.id} className="space-y-2 rounded-lg border border-zinc-200 p-3">
          <div className="flex items-start gap-2">
            <WebhookIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-500" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-zinc-900">
                {h.name} {!h.enabled && <span className="ml-1 rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500">Off</span>}
              </p>
              <p className="truncate font-mono text-[11px] text-zinc-500">…/public/hooks/{h.token_prefix}…</p>
              <p className="text-[11px] text-zinc-400">
                {h.last_used_at ? `Last called ${new Date(h.last_used_at).toLocaleString()}` : "Never called yet"} · {h.requests_per_minute}/min
              </p>
              {h.instruction && <p className="mt-1 line-clamp-2 text-[11px] text-zinc-600">“{h.instruction}”</p>}
            </div>
            <div className="flex shrink-0 gap-1">
              <button type="button" title={h.enabled ? "Turn off" : "Turn on"} aria-label={h.enabled ? "Turn off" : "Turn on"} onClick={() => toggle.mutate(h)} className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 cursor-pointer">
                {h.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              </button>
              <button
                type="button"
                title="Delete"
                aria-label="Delete webhook"
                onClick={() => window.confirm("Delete this webhook? Anything still calling its URL will get an error.") && remove.mutate(h)}
                className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-red-600 cursor-pointer"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          {created?.id === h.id && (
            <div className="space-y-1.5 rounded-lg border border-emerald-200 bg-emerald-50 p-2.5">
              <p className="text-xs font-medium text-emerald-800">Copy this URL now — it won&apos;t be shown again.</p>
              <CopyField value={created.url} />
              <p className="text-[11px] text-emerald-800">
                Try it: <code className="break-all">curl -X POST -H &quot;Content-Type: application/json&quot; -d &apos;{`{"text":"hello"}`}&apos; &lt;url&gt;</code>
              </p>
            </div>
          )}
        </div>
      ))}
      {adding && (
        <form
          className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/40 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Name" hint="So you can tell them apart: where it's called from.">
            <Input className="h-8 text-xs" maxLength={120} value={draft.name} placeholder="Website contact form" onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </Field>
          <Field label="What to do with each post (optional)" hint="Put before what was posted. A text, message or input field is used as is; other fields are listed.">
            <Textarea rows={2} maxLength={2000} value={draft.instruction} placeholder="A new lead came in. Qualify it and draft a reply:" onChange={(e) => setDraft({ ...draft, instruction: e.target.value })} />
          </Field>
          <Field label="Most calls per minute">
            <Input className="h-8 w-24 text-xs" type="number" min={1} max={60} value={draft.requests_per_minute} onChange={(e) => setDraft({ ...draft, requests_per_minute: Math.max(1, Math.min(60, Number(e.target.value) || 10)) })} />
          </Field>
          <div className="flex gap-2">
            <button type="submit" disabled={create.isPending} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-indigo-600 px-3 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 cursor-pointer">
              {create.isPending && <Spinner className="h-3.5 w-3.5" />} Create webhook
            </button>
            <button type="button" onClick={() => setAdding(false)} className="h-8 rounded-md px-3 text-xs text-zinc-600 hover:bg-zinc-100 cursor-pointer">Cancel</button>
          </div>
          <p className="text-[11px] text-zinc-500">It runs as you, with your connected accounts, and asks you before data-changing tools as usual. Results land in the agent&apos;s run history.</p>
        </form>
      )}
    </Section>
  );
}
