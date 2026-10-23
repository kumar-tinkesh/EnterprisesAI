"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, ChevronRight, Code2, Copy, ExternalLink, Link2, MessageSquare, Send, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { Field, Select, Textarea } from "@/components/builder/fields";
import { timeAgo } from "@/components/builder/version-history";
import { ApiError } from "@/lib/api";
import { PUBLIC_API_URL, builderApi, shareUrl } from "@/lib/builder/api";
import type { PublicKey, PublicKeyCreated, ToolMode, ToolNeedStatus } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** The three ways to publish. Each one is a public key underneath; they differ in what's switched on. */
export type Way = "link" | "website" | "api";

export const WAYS: { way: Way; Icon: typeof Link2; title: string; hint: string; defaultName: string; action: string }[] = [
  { way: "link", Icon: Link2, title: "Share link", hint: "Send people a link. They sign in and use it.", defaultName: "Share link", action: "Publish link" },
  { way: "website", Icon: MessageSquare, title: "Website chat", hint: "A chat bubble on your own website.", defaultName: "Website", action: "Get website code" },
  { way: "api", Icon: Code2, title: "API", hint: "Call it from your app or server.", defaultName: "API", action: "Create API key" },
];

export const wayOf = (k: PublicKey): Way => (k.share_enabled ? "link" : k.allowed_origins.length ? "website" : "api");

function CopyButton({ text, label = "Copy", primary }: { text: string; label?: string; primary?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm"
      variant={primary ? "default" : "outline"}
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? <Check /> : <Copy />} {done ? "Copied" : label}
    </Button>
  );
}

function snippets(key: string, title: string) {
  return {
    website: `<script src="${PUBLIC_API_URL}/widget.js"\n        data-key="${key}"\n        data-title="${title.replace(/"/g, "&quot;")}"></script>`,
    curl: `# The whole answer (waits up to 20 s, then poll GET /runs/{run_id}):\ncurl -X POST ${PUBLIC_API_URL}/runs \\\n  -H "Authorization: Bearer ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"input": "Hello", "wait_seconds": 20, "stream": false}'\n\n# Or watch it being written: start with "wait_seconds": 0, then\ncurl -N ${PUBLIC_API_URL}/runs/RUN_ID/events -H "Authorization: Bearer ${key}"`,
    javascript: `const headers = { Authorization: "Bearer ${key}", "Content-Type": "application/json" };\nconst start = await fetch("${PUBLIC_API_URL}/runs", {\n  method: "POST", headers,\n  body: JSON.stringify({ input: "Hello", wait_seconds: 0 }), // streaming is on unless "stream": false\n});\nconst { run_id } = await start.json();\n\n// Server-Sent Events: "delta" = the next piece of the answer, "run" = its state (status, output).\nconst res = await fetch(\`${PUBLIC_API_URL}/runs/\${run_id}/events\`, { headers });\nconst reader = res.body.getReader();\nconst decoder = new TextDecoder();\nfor (let r; !(r = await reader.read()).done; ) console.log(decoder.decode(r.value));`,
  };
}

function Code({ text }: { text: string }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md border border-zinc-200 bg-[var(--bg)] p-3 pr-24 font-mono text-xs leading-relaxed text-zinc-700">{text}</pre>
      <div className="absolute right-2 top-2"><CopyButton text={text} /></div>
    </div>
  );
}

/**
 * Publish an agent/workflow. Three steps: pick how (share link, website chat,
 * API), set the one or two things that way needs (the rest under Advanced),
 * then copy what you got. What's already published is listed on the first screen.
 */
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
  const [way, setWay] = useState<Way | null>(null);
  const [pin, setPin] = useState<"latest" | number>("latest");
  const [keyName, setKeyName] = useState("");
  const [origins, setOrigins] = useState("");
  const [rpm, setRpm] = useState(20);
  const [quota, setQuota] = useState("");
  const [ack, setAck] = useState(false);
  const [perUser, setPerUser] = useState("");
  const [toolMode, setToolMode] = useState<ToolMode>("publisher");
  const [keepMine, setKeepMine] = useState<string[]>([]);
  const [showOutline, setShowOutline] = useState(true);
  const [created, setCreated] = useState<{ key: PublicKeyCreated; way: Way } | null>(null);
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

  const start = (w: Way) => {
    setWay(w);
    setKeyName(WAYS.find((x) => x.way === w)!.defaultName);
    setOrigins("");
    setAck(false);
    setError(null);
  };
  const reset = () => {
    setWay(null);
    setCreated(null);
    setError(null);
  };

  const writeTools = check.data?.write_tools ?? [];
  const create = useMutation({
    mutationFn: (w: Way) =>
      builderApi.createPublicKey(token, kind, targetId, {
        name: keyName.trim() || WAYS.find((x) => x.way === w)!.defaultName,
        version: pin === "latest" ? null : pin,
        allowed_origins: origins.split(/[\s,]+/).map((o) => o.trim()).filter(Boolean),
        requests_per_minute: rpm,
        daily_quota: quota.trim() ? Number(quota) : null,
        acknowledge_write_tools: ack,
        share: w === "link",
        per_user_daily_limit: w === "link" && perUser.trim() ? Number(perUser) : null,
        tool_mode: toolMode,
        publisher_server_ids: toolMode === "mixed" ? keepMine : [],
        show_outline: w === "link" ? showOutline : true,
      }),
    onSuccess: (k, w) => {
      setCreated({ key: k, way: w });
      setError(null);
      void refresh();
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: "active" | "paused"; share?: boolean; tool_mode?: ToolMode; publisher_server_ids?: string[]; show_outline?: boolean }) =>
      builderApi.updatePublicKey(token, id, body),
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const revoke = useMutation({ mutationFn: (id: string) => builderApi.revokePublicKey(token, id), onSuccess: () => void refresh(), onError: fail });

  const live = (keys.data ?? []).filter((k) => k.status !== "revoked");
  const problems = check.data?.problems ?? [];
  const current = WAYS.find((x) => x.way === way);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3">
        {way && !created && (
          <button type="button" aria-label="Back" onClick={reset} className="-ml-1 rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
            <ArrowLeft className="h-4 w-4" />
          </button>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-zinc-900">{created ? "You're live" : current ? current.title : "Publish"}</h2>
          {!way && <p className="text-sm text-zinc-500">Let people or apps use this {kind}.</p>}
        </div>
        <button type="button" aria-label="Close" onClick={onClose} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"><X className="h-4 w-4" /></button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {/* One banner for "it won't work yet", shown before anything else. */}
        {!created && problems.length > 0 && (
          <Notice tone="danger" title="Fix this first — it can't run right now">
            {problems.map((p) => <p key={p}>{p}</p>)}
          </Notice>
        )}
        {dirty && !created && <Notice tone="warning" title="You have unsaved changes">Publishing uses the last saved version. Save first to include them.</Notice>}

        {created ? (
          <Done created={created.key} way={created.way} name={name} onDone={reset} />
        ) : !way ? (
          <>
            <div className="space-y-2">
              {WAYS.map(({ way: w, Icon, title, hint }) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => start(w)}
                  className="flex w-full items-center gap-3 rounded-lg border border-zinc-200 p-3 text-left transition-colors hover:border-zinc-300 hover:bg-zinc-50 cursor-pointer"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-zinc-700"><Icon className="h-4 w-4" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-zinc-900">{title}</span>
                    <span className="block text-xs text-zinc-500">{hint}</span>
                  </span>
                  <ChevronRight className="h-4 w-4 text-zinc-400" />
                </button>
              ))}
            </div>

            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-zinc-900">Published {live.length > 0 && <span className="font-normal text-zinc-500">· {live.length}</span>}</h3>
              {keys.isLoading && <Spinner className="h-4 w-4 text-zinc-400" />}
              {!keys.isLoading && live.length === 0 && <p className="text-sm text-zinc-500">Nothing yet. Pick a way above.</p>}
              <ul className="space-y-2">
                {live.map((k) => (
                  <PublishedItem
                    key={k.id}
                    item={k}
                    systems={check.data?.systems ?? []}
                    onUpdate={(body) => update.mutate({ id: k.id, ...body })}
                    onRevoke={() => window.confirm(`Delete "${k.name}"? Anyone using it stops at once.`) && revoke.mutate(k.id)}
                  />
                ))}
              </ul>
              {error && <p className="text-sm text-red-600">{error}</p>}
            </section>
          </>
        ) : (
          <div className="space-y-4">
            {way === "link" && (
              <ShareModePicker name="new-key" mode={toolMode} mine={keepMine} systems={check.data?.systems ?? []} onChange={(c) => {
                if (c.tool_mode) setToolMode(c.tool_mode);
                if (c.publisher_server_ids) setKeepMine(c.publisher_server_ids);
              }} />
            )}
            {way === "link" && (
              <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-zinc-200 p-3">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={showOutline} onChange={(e) => setShowOutline(e.target.checked)} />
                <span>
                  <span className="block text-sm font-medium text-zinc-900">Show how it works</span>
                  <span className="block text-xs text-zinc-500">People see its steps and the apps each uses — never your instructions.</span>
                </span>
              </label>
            )}
            {way === "website" && (
              <Field label="Your website" hint="Only these sites can show the chat. One per line. Leave empty to allow any site.">
                <Textarea rows={2} value={origins} placeholder="https://acme.com" onChange={(e) => setOrigins(e.target.value)} />
              </Field>
            )}
            {way === "api" && <p className="text-sm text-zinc-500">You&apos;ll get a secret key and ready-to-paste code.</p>}

            {(check.data?.advice ?? []).map((a) => <Notice key={a} tone="warning">{a}</Notice>)}

            {writeTools.length > 0 && (
              <Notice tone="warning" title="It can change data in your apps">
                <p>People using it can trigger: <span className="font-mono">{writeTools.join(", ")}</span>. Steps that need your approval still wait for you.</p>
                <label className="mt-2 flex cursor-pointer items-center gap-2 text-zinc-900">
                  <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  I understand
                </label>
              </Notice>
            )}

            <details className="group rounded-lg border border-zinc-200">
              <summary className="flex cursor-pointer select-none items-center gap-1.5 px-3 py-2.5 text-sm font-medium text-zinc-700 [&::-webkit-details-marker]:hidden">
                <ChevronRight className="h-4 w-4 text-zinc-400 transition-transform group-open:rotate-90" /> Advanced
              </summary>
              <div className="space-y-3 border-t border-zinc-200 p-3">
                <Field label="Name" hint="Only you see this.">
                  <Input value={keyName} maxLength={120} onChange={(e) => setKeyName(e.target.value)} />
                </Field>
                <Field label="Version">
                  <Select value={pin} onChange={(e) => setPin(e.target.value === "latest" ? "latest" : Number(e.target.value))}>
                    <option value="latest">Always the latest saved (v{currentVersion})</option>
                    {(versions.data ?? []).map((v) => (
                      <option key={v.id} value={v.version}>Stay on v{v.version} — {v.note.toLowerCase()} {timeAgo(v.created_at)}</option>
                    ))}
                  </Select>
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Runs a day">
                    <Input type="number" min={1} placeholder="No limit" value={quota} onChange={(e) => setQuota(e.target.value)} />
                  </Field>
                  {way === "link" ? (
                    <Field label="Runs a day per person">
                      <Input type="number" min={1} placeholder="No limit" value={perUser} onChange={(e) => setPerUser(e.target.value)} />
                    </Field>
                  ) : (
                    <Field label="Requests a minute">
                      <Input type="number" min={1} max={600} value={rpm} onChange={(e) => setRpm(Math.max(1, Number(e.target.value) || 1))} />
                    </Field>
                  )}
                </div>
                {way === "api" && (
                  <Field label="Allowed websites" hint="Leave empty for servers and any site.">
                    <Textarea rows={2} value={origins} placeholder="https://acme.com" onChange={(e) => setOrigins(e.target.value)} />
                  </Field>
                )}
              </div>
            </details>

            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button className="w-full" disabled={create.isPending || (writeTools.length > 0 && !ack)} onClick={() => create.mutate(way)}>
              {create.isPending && <Spinner className="h-4 w-4" />} {current!.action}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** A coloured note: danger for "won't work", warning for "careful". */
function Notice({ tone, title, children }: { tone: "danger" | "warning"; title?: string; children: React.ReactNode }) {
  return (
    <div className={cn("flex gap-2.5 rounded-lg border p-3 text-sm", tone === "danger" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50")}>
      <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", tone === "danger" ? "text-red-600" : "text-amber-700")} />
      <div className="min-w-0 space-y-1 text-zinc-700">
        {title && <p className="font-medium text-zinc-900">{title}</p>}
        {children}
      </div>
    </div>
  );
}

/** After publishing: the one thing to copy, big, and a way to try it. */
function Done({ created, way, name, onDone }: { created: PublicKeyCreated; way: Way; name: string; onDone: () => void }) {
  const [tab, setTab] = useState<"curl" | "javascript">("curl");
  const code = snippets(created.key, name);
  return (
    <div className="space-y-5">
      {way === "link" && created.share_slug && (
        <section className="space-y-2">
          <p className="text-sm text-zinc-500">Send this link. Whoever opens it signs in and can use it.</p>
          <div className="truncate rounded-md border border-zinc-200 bg-[var(--bg)] px-3 py-2.5 font-mono text-sm text-zinc-900">{shareUrl(created.share_slug)}</div>
          <div className="flex gap-2">
            <CopyButton text={shareUrl(created.share_slug)} label="Copy link" primary />
            <a href={shareUrl(created.share_slug)} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-2 rounded-md border border-[var(--border-strong)] px-3 text-sm font-medium text-zinc-900 hover:bg-zinc-50">
              <ExternalLink className="h-4 w-4" /> Open
            </a>
          </div>
        </section>
      )}

      {way === "website" && (
        <section className="space-y-2">
          <p className="text-sm text-zinc-500">Paste this just before <span className="font-mono">&lt;/body&gt;</span> on your site. A chat bubble appears in the corner.</p>
          <Code text={code.website} />
        </section>
      )}

      {way === "api" && (
        <section className="space-y-3">
          <div className="space-y-2">
            <p className="text-sm text-zinc-500">Your secret key. Copy it now — it won&apos;t be shown again.</p>
            <div className="break-all rounded-md border border-zinc-200 bg-[var(--bg)] px-3 py-2.5 font-mono text-sm text-zinc-900">{created.key}</div>
            <CopyButton text={created.key} label="Copy key" primary />
          </div>
          <div className="flex gap-1 border-b border-zinc-200" role="tablist">
            {(["curl", "javascript"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("-mb-px border-b-2 px-3 py-2 text-sm cursor-pointer", tab === t ? "border-[var(--accent-hover)] text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-900")}>
                {t === "curl" ? "curl" : "JavaScript"}
              </button>
            ))}
          </div>
          <Code text={code[tab]} />
        </section>
      )}

      {way !== "link" && <TryIt apiKey={created.key} />}
      <Button variant="outline" className="w-full" onClick={onDone}>Done</Button>
    </div>
  );
}

/** One published way in the list: what it is, whether it's on, and a ⋯ menu for the rest. */
function PublishedItem({
  item: k, systems, onUpdate, onRevoke,
}: {
  item: PublicKey;
  systems: ToolNeedStatus[];
  onUpdate: (body: { status?: "active" | "paused"; share?: boolean; tool_mode?: ToolMode; publisher_server_ids?: string[]; show_outline?: boolean }) => void;
  onRevoke: () => void;
}) {
  const [accounts, setAccounts] = useState(false);
  const w = wayOf(k);
  const { Icon } = WAYS.find((x) => x.way === w)!;
  const active = k.status === "active";
  const url = k.share_enabled && k.share_slug ? shareUrl(k.share_slug) : null;

  return (
    <li className="rounded-lg border border-zinc-200 p-3">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-sm font-medium text-zinc-900">
            <span className="truncate">{k.name}</span>
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", active ? "bg-emerald-50 text-emerald-700" : "bg-zinc-100 text-zinc-500")}>{active ? "Live" : "Paused"}</span>
          </p>
          {url ? (
            <a href={url} target="_blank" rel="noopener noreferrer" className="block truncate font-mono text-xs text-[var(--link)] hover:underline">{url}</a>
          ) : (
            <p className="font-mono text-xs text-zinc-500">{k.key_prefix}…</p>
          )}
          <p className="mt-0.5 text-xs text-zinc-500">
            {k.runs_today} run{k.runs_today === 1 ? "" : "s"} today{k.daily_quota ? ` of ${k.daily_quota}` : ""}
            {k.last_used_at ? ` · used ${timeAgo(k.last_used_at)}` : ""}
            {k.version ? ` · v${k.version}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {url && <IconCopy text={url} />}
          <Menu
            label={`More for ${k.name}`}
            items={[
              { label: active ? "Pause" : "Resume", onClick: () => onUpdate({ status: active ? "paused" : "active" }) },
              ...(k.share_enabled
                ? [
                    { label: "Whose accounts it uses", onClick: () => setAccounts((v) => !v) },
                    { label: "Show how it works", checked: k.show_outline, onClick: () => onUpdate({ show_outline: !k.show_outline }) },
                  ]
                : []),
              { label: k.share_enabled ? "Turn off share link" : "Turn on share link", onClick: () => onUpdate({ share: !k.share_enabled }) },
              { label: "Delete", onClick: onRevoke, danger: true },
            ]}
          />
        </div>
      </div>
      {accounts && k.share_enabled && (
        <div className="mt-3 border-t border-zinc-200 pt-3">
          <ShareModePicker name={`key-${k.id}`} mode={k.tool_mode} mine={k.publisher_server_ids} systems={systems} onChange={onUpdate} />
        </div>
      )}
    </li>
  );
}

export function IconCopy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      title="Copy link"
      aria-label="Copy link"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"
    >
      {done ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

const MODES: [ToolMode, string, string][] = [
  ["publisher", "Mine", "Everyone uses your connected accounts. Changes wait for your approval."],
  ["visitor", "Each person's own", "People connect their own accounts and approve their own runs."],
  ["mixed", "Some mine, some theirs", "Pick the apps that use your account. People connect the rest."],
];

/** Whose connected apps a share link uses — and on a mixed one, which apps stay yours. */
function ShareModePicker({
  name, mode, mine, systems, onChange,
}: {
  name: string;
  mode: ToolMode;
  mine: string[];
  systems: ToolNeedStatus[];
  onChange: (change: { tool_mode?: ToolMode; publisher_server_ids?: string[] }) => void;
}) {
  // The mixed choice only matters when it uses connected apps.
  const modes = systems.length > 0 || mode === "mixed" ? MODES : MODES.slice(0, 2);
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium text-zinc-700">Whose accounts does it use?</legend>
      {modes.map(([value, label, hint]) => (
        <label
          key={value}
          className={cn("flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors", mode === value ? "border-[var(--accent-border)] bg-[var(--accent-wash)]" : "border-zinc-200 hover:bg-zinc-50")}
        >
          <input type="radio" name={`tool-mode-${name}`} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={mode === value} onChange={() => onChange({ tool_mode: value })} />
          <span>
            <span className="block text-sm font-medium text-zinc-900">{label}</span>
            <span className="block text-xs text-zinc-500">{hint}</span>
          </span>
        </label>
      ))}
      {mode === "mixed" && (
        <div className="space-y-2 rounded-lg bg-zinc-50 p-3">
          <p className="text-xs font-medium text-zinc-700">Use my account for:</p>
          {systems.map((sys) => (
            <label key={sys.server_id!} className="flex cursor-pointer items-center gap-2 text-sm text-zinc-900">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--accent)]"
                checked={mine.includes(sys.server_id!)}
                onChange={(e) => onChange({ publisher_server_ids: e.target.checked ? [...mine, sys.server_id!] : mine.filter((x) => x !== sys.server_id) })}
              />
              {sys.server_name || sys.system}
              {sys.status !== "ready" && <span className="text-xs text-amber-700">not connected</span>}
            </label>
          ))}
        </div>
      )}
    </fieldset>
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
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-zinc-900">Try it</h3>
      <div className="flex gap-2">
        <Input value={text} placeholder="Ask something" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && text.trim() && !busy && void ask()} />
        <Button size="default" disabled={busy || !text.trim()} onClick={() => void ask()} aria-label="Send test message">
          {busy ? <Spinner className="h-4 w-4" /> : <Send />}
        </Button>
      </div>
      {answer !== null && <p className="whitespace-pre-wrap rounded-md bg-zinc-50 p-3 text-sm text-zinc-700">{answer}</p>}
    </section>
  );
}
