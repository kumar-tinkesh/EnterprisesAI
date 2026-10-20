"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, Globe, KeyRound, Link2, Pause, Play, Send, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Select, Textarea, Toggle } from "@/components/builder/fields";
import { timeAgo } from "@/components/builder/version-history";
import { ApiError } from "@/lib/api";
import { PUBLIC_API_URL, builderApi, shareUrl } from "@/lib/builder/api";
import type { PublicKey, PublicKeyCreated, ToolMode, ToolNeedStatus } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="inline-flex items-center gap-1 rounded border border-zinc-200 bg-white px-1.5 py-0.5 text-[11px] text-zinc-600 hover:text-zinc-900 cursor-pointer"
    >
      {done ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} {done ? "Copied" : label}
    </button>
  );
}

function snippets(key: string, title: string) {
  return {
    website: `<script src="${PUBLIC_API_URL}/widget.js"\n        data-key="${key}"\n        data-title="${title.replace(/"/g, "&quot;")}"></script>`,
    curl: `# The whole answer (waits up to 20 s, then poll GET /runs/{run_id}):\ncurl -X POST ${PUBLIC_API_URL}/runs \\\n  -H "Authorization: Bearer ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"input": "Hello", "wait_seconds": 20, "stream": false}'\n\n# Or watch it being written: start with "wait_seconds": 0, then\ncurl -N ${PUBLIC_API_URL}/runs/RUN_ID/events -H "Authorization: Bearer ${key}"`,
    javascript: `const headers = { Authorization: "Bearer ${key}", "Content-Type": "application/json" };\nconst start = await fetch("${PUBLIC_API_URL}/runs", {\n  method: "POST", headers,\n  body: JSON.stringify({ input: "Hello", wait_seconds: 0 }), // streaming is on unless "stream": false\n});\nconst { run_id } = await start.json();\n\n// Server-Sent Events: "delta" = the next piece of the answer, "run" = its state (status, output).\nconst res = await fetch(\`${PUBLIC_API_URL}/runs/\${run_id}/events\`, { headers });\nconst reader = res.body.getReader();\nconst decoder = new TextDecoder();\nfor (let r; !(r = await reader.read()).done; ) console.log(decoder.decode(r.value));`,
  };
}

/** Publish an agent/workflow: publishable keys for apps and websites, with a chat widget. */
export function PublishPanel({
  kind,
  targetId,
  name,
  token,
  currentVersion,
  dirty,
  onClose,
}: {
  kind: "agent" | "workflow";
  targetId: string;
  name: string;
  token: string;
  currentVersion: number;
  dirty: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const keysKey = ["builder-public-keys", kind, targetId];
  const [pin, setPin] = useState<"latest" | number>("latest");
  const [keyName, setKeyName] = useState("Website");
  const [origins, setOrigins] = useState("");
  const [rpm, setRpm] = useState(20);
  const [quota, setQuota] = useState("");
  const [ack, setAck] = useState(false);
  const [share, setShare] = useState(true);
  const [perUser, setPerUser] = useState("");
  const [toolMode, setToolMode] = useState<ToolMode>("publisher");
  const [keepMine, setKeepMine] = useState<string[]>([]);
  const [created, setCreated] = useState<PublicKeyCreated | null>(null);
  const [tab, setTab] = useState<"website" | "curl" | "javascript">("website");
  const [error, setError] = useState<string | null>(null);

  const versions = useQuery({ queryKey: ["builder-versions", kind, targetId], queryFn: () => builderApi.listVersions(token, kind, targetId), enabled: !!token });
  const check = useQuery({
    queryKey: ["builder-publish-check", kind, targetId, pin],
    queryFn: () => builderApi.publishCheck(token, kind, targetId, pin === "latest" ? null : pin),
    enabled: !!token,
  });
  const keys = useQuery({ queryKey: keysKey, queryFn: () => builderApi.listPublicKeys(token, kind, targetId), enabled: !!token });
  const refresh = () => queryClient.invalidateQueries({ queryKey: keysKey });
  const fail = (err: unknown) => {
    const detail = err instanceof ApiError ? (err.body as { detail?: { message?: string } | string })?.detail : null;
    setError(typeof detail === "object" && detail?.message ? detail.message : err instanceof Error ? err.message : "Something went wrong.");
  };

  const writeTools = check.data?.write_tools ?? [];
  const create = useMutation({
    mutationFn: () =>
      builderApi.createPublicKey(token, kind, targetId, {
        name: keyName.trim() || "Public key",
        version: pin === "latest" ? null : pin,
        allowed_origins: origins.split(/[\s,]+/).map((o) => o.trim()).filter(Boolean),
        requests_per_minute: rpm,
        daily_quota: quota.trim() ? Number(quota) : null,
        acknowledge_write_tools: ack,
        share,
        per_user_daily_limit: share && perUser.trim() ? Number(perUser) : null,
        tool_mode: toolMode,
        publisher_server_ids: toolMode === "mixed" ? keepMine : [],
      }),
    onSuccess: (k) => {
      setCreated(k);
      setError(null);
      void refresh();
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: "active" | "paused"; share?: boolean; tool_mode?: ToolMode; publisher_server_ids?: string[] }) =>
      builderApi.updatePublicKey(token, id, body),
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const revoke = useMutation({ mutationFn: (id: string) => builderApi.revokePublicKey(token, id), onSuccess: () => void refresh(), onError: fail });

  const live = (keys.data ?? []).filter((k) => k.status !== "revoked");

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-zinc-200 px-4 py-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900"><Globe className="h-4 w-4" /> Publish</h2>
          <p className="text-xs text-zinc-500">Send a link anyone can use after signing in, or let apps and websites call it with a key.</p>
        </div>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer"><X className="h-4 w-4" /></button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {created ? (
          <div className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
            {created.share_enabled && created.share_slug && <ShareLink slug={created.share_slug} />}
            <p className="text-sm font-semibold text-emerald-900">Published — copy the key now</p>
            <p className="text-xs text-emerald-900">It won&apos;t be shown again. It only runs this {kind}, so it can sit in a web page.</p>
            <div className="flex items-center gap-2 rounded bg-white p-2 font-mono text-xs break-all">
              <span className="flex-1">{created.key}</span>
              <CopyButton text={created.key} />
            </div>
            <div className="flex gap-1 text-xs" role="tablist">
              {(["website", "curl", "javascript"] as const).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded px-2 py-1 capitalize cursor-pointer", tab === t ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}>
                  {t === "website" ? "Website chat" : t === "curl" ? "API (curl)" : "JavaScript"}
                </button>
              ))}
            </div>
            <div className="relative">
              <pre className="overflow-x-auto rounded bg-zinc-900 p-2.5 pt-8 text-[11px] leading-relaxed text-zinc-100">{snippets(created.key, name)[tab]}</pre>
              <div className="absolute right-1.5 top-1.5"><CopyButton text={snippets(created.key, name)[tab]} /></div>
            </div>
            {tab === "website" && <p className="text-[11px] text-zinc-600">Paste before &lt;/body&gt;: a chat bubble appears in the corner. Each message is answered on its own.</p>}
            <TryIt apiKey={created.key} />
            <Button size="sm" variant="outline" onClick={() => setCreated(null)}>Done</Button>
          </div>
        ) : (
          <div className="space-y-3">
            {dirty && <p className="rounded bg-amber-50 p-2 text-xs text-amber-900">You have unsaved changes — publishing uses saved versions.</p>}
            <Field label="Which version">
              <Select value={pin} onChange={(e) => setPin(e.target.value === "latest" ? "latest" : Number(e.target.value))}>
                <option value="latest">Always the latest saved (now v{currentVersion})</option>
                {(versions.data ?? []).map((v) => (
                  <option key={v.id} value={v.version}>Pin v{v.version} — {v.note.toLowerCase()} {timeAgo(v.created_at)}</option>
                ))}
              </Select>
            </Field>

            {check.isLoading && <Spinner className="h-4 w-4 text-zinc-400" />}
            {(check.data?.problems ?? []).length > 0 && (
              <div className="space-y-1 rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs text-red-800">
                <p className="font-semibold">It can&apos;t run right now — callers will get an error until this is fixed:</p>
                {check.data!.problems.map((p) => <p key={p}>• {p}</p>)}
              </div>
            )}
            {(check.data?.advice ?? []).map((a) => (
              <p key={a} className="flex gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{a}</p>
            ))}
            {writeTools.length > 0 && (
              <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-2.5 text-xs text-amber-950">
                <p className="font-semibold">
                  Anyone with the key could make it use tools that change data — with your accounts{share && toolMode !== "publisher" ? " (through the API and website chat; the share link uses each person's own, except apps you keep)" : ""}:
                </p>
                <p className="font-mono">{writeTools.join(", ")}</p>
                <p>Calls that need your approval still wait for you (you&apos;ll see them in your approvals).</p>
                <label className="flex cursor-pointer items-start gap-2">
                  <input type="checkbox" className="mt-0.5 h-4 w-4 accent-indigo-600" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  <span>I understand — publish anyway.</span>
                </label>
              </div>
            )}

            <div className="space-y-2 rounded-lg border border-zinc-200 p-2.5">
              <Toggle checked={share} onChange={setShare} label="Share link — anyone can use it after signing in" />
              {share && (
                <>
                  <ShareModePicker
                    name="new-key"
                    mode={toolMode}
                    mine={keepMine}
                    systems={check.data?.systems ?? []}
                    onChange={(c) => {
                      if (c.tool_mode) setToolMode(c.tool_mode);
                      if (c.publisher_server_ids) setKeepMine(c.publisher_server_ids);
                    }}
                  />
                  <Field label="Runs a day per person">
                    <Input className="h-9" type="number" min={1} placeholder="No limit" value={perUser} onChange={(e) => setPerUser(e.target.value)} />
                  </Field>
                </>
              )}
            </div>
            <Field label="Key name">
              <Input className="h-9" value={keyName} maxLength={120} onChange={(e) => setKeyName(e.target.value)} />
            </Field>
            <Field label="Websites allowed to use it" hint="One per line, like https://acme.com. Empty = any site, and servers.">
              <Textarea rows={2} value={origins} placeholder="https://acme.com" onChange={(e) => setOrigins(e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Requests a minute">
                <Input className="h-9" type="number" min={1} max={600} value={rpm} onChange={(e) => setRpm(Math.max(1, Number(e.target.value) || 1))} />
              </Field>
              <Field label="Runs a day">
                <Input className="h-9" type="number" min={1} placeholder="No limit" value={quota} onChange={(e) => setQuota(e.target.value)} />
              </Field>
            </div>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <Button size="sm" disabled={create.isPending || (writeTools.length > 0 && !ack)} onClick={() => create.mutate()}>
              {create.isPending ? <Spinner className="h-4 w-4" /> : <KeyRound />} Create key
            </Button>
          </div>
        )}

        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">Keys ({live.length})</p>
          {live.length === 0 && <p className="text-xs text-zinc-400">Not published yet.</p>}
          <ul className="space-y-2">
            {live.map((k: PublicKey) => (
              <li key={k.id} className="rounded-lg border border-zinc-200 p-2.5">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-zinc-900">
                      {k.name} <span className={cn("ml-1 rounded px-1.5 py-0.5 text-[10px] font-semibold", k.status === "active" ? "bg-emerald-100 text-emerald-800" : "bg-zinc-100 text-zinc-600")}>{k.status}</span>
                    </p>
                    <p className="font-mono text-[11px] text-zinc-500">{k.key_prefix}…</p>
                    <p className="text-[11px] text-zinc-500">
                      {k.version ? `Pinned v${k.version}` : "Latest version"} · {k.runs_today} run{k.runs_today === 1 ? "" : "s"} today
                      {k.daily_quota ? ` / ${k.daily_quota}` : ""} · {k.requests_per_minute}/min
                      {k.last_used_at ? ` · used ${timeAgo(k.last_used_at)}` : ""}
                    </p>
                    {k.allowed_origins.length > 0 && <p className="truncate text-[11px] text-zinc-500">Sites: {k.allowed_origins.join(", ")}</p>}
                    {k.share_enabled && k.share_slug && (
                      <div className="mt-1.5 space-y-1">
                        <ShareLink slug={k.share_slug} compact />
                        <details className="text-[11px] text-zinc-500">
                          <summary className="cursor-pointer select-none">
                            Uses {k.tool_mode === "visitor" ? "each person's own apps" : k.tool_mode === "mixed" ? `their apps, except ${k.publisher_server_ids.length} of yours` : "your apps"} · change
                          </summary>
                          <div className="mt-1.5">
                            <ShareModePicker
                              name={`key-${k.id}`}
                              mode={k.tool_mode}
                              mine={k.publisher_server_ids}
                              systems={check.data?.systems ?? []}
                              onChange={(c) => update.mutate({ id: k.id, ...c })}
                            />
                          </div>
                        </details>
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      title={k.share_enabled ? "Turn the share link off" : "Make a share link"}
                      aria-label={k.share_enabled ? `Turn off the share link of ${k.name}` : `Make a share link for ${k.name}`}
                      aria-pressed={k.share_enabled}
                      onClick={() => update.mutate({ id: k.id, share: !k.share_enabled })}
                      className={cn("rounded p-1 hover:bg-zinc-100 cursor-pointer", k.share_enabled ? "text-indigo-500 hover:text-indigo-400" : "text-zinc-400 hover:text-zinc-800")}
                    >
                      <Link2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title={k.status === "active" ? "Pause" : "Resume"}
                      aria-label={k.status === "active" ? `Pause ${k.name}` : `Resume ${k.name}`}
                      onClick={() => update.mutate({ id: k.id, status: k.status === "active" ? "paused" : "active" })}
                      className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 cursor-pointer"
                    >
                      {k.status === "active" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                    </button>
                    <button
                      type="button"
                      title="Revoke"
                      aria-label={`Revoke ${k.name}`}
                      onClick={() => window.confirm(`Revoke "${k.name}"? Apps and sites using it stop working at once.`) && revoke.mutate(k.id)}
                      className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-red-600 cursor-pointer"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

const MODES: [ToolMode, string, string][] = [
  ["publisher", "Mine", "Everyone uses your accounts. Anything that would change data waits for your approval."],
  ["visitor", "Each person's own", "They connect their own accounts on the link page and approve their own runs. You see who used it, not what was in it."],
  ["mixed", "Some mine, some theirs", "Pick the apps that stay yours (your account, your approval). They connect the rest and approve those themselves."],
];

/** Whose apps a share link uses — and on a mixed one, which apps stay yours. */
function ShareModePicker({
  name, mode, mine, systems, onChange,
}: {
  name: string;
  mode: ToolMode;
  mine: string[];
  systems: ToolNeedStatus[];
  onChange: (change: { tool_mode?: ToolMode; publisher_server_ids?: string[] }) => void;
}) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="mb-1 text-xs font-medium text-zinc-700">Whose connected apps it uses</legend>
      {MODES.map(([value, label, hint]) => (
        <label key={value} className="flex cursor-pointer items-start gap-2">
          <input type="radio" name={`tool-mode-${name}`} className="mt-0.5 h-4 w-4 accent-indigo-600" checked={mode === value} onChange={() => onChange({ tool_mode: value })} />
          <span>
            <span className="block text-sm text-zinc-800">{label}</span>
            <span className="block text-[11px] text-zinc-500">{hint}</span>
          </span>
        </label>
      ))}
      {mode === "mixed" && (
        <div className="ml-6 space-y-1 rounded-md bg-zinc-50 p-2">
          <p className="text-[11px] font-medium text-zinc-700">Use my account for:</p>
          {systems.length === 0 && <p className="text-[11px] text-zinc-500">It doesn&apos;t use any connected apps.</p>}
          {systems.map((sys) => (
            <label key={sys.server_id!} className="flex cursor-pointer items-center gap-2 text-xs text-zinc-800">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-indigo-600"
                checked={mine.includes(sys.server_id!)}
                onChange={(e) => onChange({ publisher_server_ids: e.target.checked ? [...mine, sys.server_id!] : mine.filter((x) => x !== sys.server_id) })}
              />
              {sys.server_name || sys.system}
              {sys.status !== "ready" && <span className="text-[10px] text-amber-600">you haven&apos;t connected it</span>}
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

/** The /r/{slug} link to send people; the same link comes back if sharing is turned off and on. */
function ShareLink({ slug, compact }: { slug: string; compact?: boolean }) {
  const url = shareUrl(slug);
  return (
    <div className={cn("space-y-1", !compact && "rounded bg-white p-2")}>
      {!compact && <p className="text-xs font-semibold text-zinc-900">Share link</p>}
      <div className="flex items-center gap-2">
        <a href={url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate font-mono text-[11px] text-indigo-500 hover:text-indigo-400">{url}</a>
        <CopyButton text={url} label="Copy link" />
      </div>
      {!compact && <p className="text-[11px] text-zinc-500">Whoever opens it signs in (or signs up) and runs it.</p>}
    </div>
  );
}

/** Call the public API with the new key, the way a website would. */
function TryIt({ apiKey }: { apiKey: string }) {
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    setBusy(true);
    setAnswer(null);
    try {
      const headers = { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" };
      let res = await fetch(`${PUBLIC_API_URL}/runs`, { method: "POST", headers, body: JSON.stringify({ input: text, wait_seconds: 25 }) });
      let run = await res.json();
      for (let i = 0; res.ok && run.status !== "succeeded" && run.status !== "failed" && run.status !== "cancelled" && run.waiting_for !== "approval" && i < 60; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        res = await fetch(`${PUBLIC_API_URL}/runs/${run.run_id}`, { headers });
        run = await res.json();
      }
      setAnswer(!res.ok ? run.detail ?? "Error" : run.waiting_for === "approval" ? "Waiting for your approval (see approvals)…" : run.output ?? run.error ?? run.status);
    } catch {
      setAnswer("Couldn't reach the public API.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-1.5 rounded border border-zinc-200 bg-white p-2.5">
      <p className="text-xs font-medium text-zinc-700">Try it as a caller</p>
      <div className="flex gap-1.5">
        <Input className="h-8 text-xs" value={text} placeholder="Ask something" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && text.trim() && !busy && void ask()} />
        <Button size="sm" className="h-8" disabled={busy || !text.trim()} onClick={() => void ask()} aria-label="Send test message">
          {busy ? <Spinner className="h-3.5 w-3.5" /> : <Send />}
        </Button>
      </div>
      {answer !== null && <p className="whitespace-pre-wrap text-xs text-zinc-800">{answer}</p>}
    </div>
  );
}
