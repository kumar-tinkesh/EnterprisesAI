"use client";

/** One app (MCP server) on the admin Apps page: what it is, its setup, its tools, who can use it. */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Globe, Instagram, Lock, Plus, RefreshCw, Trash2, Unlink, Wrench, X } from "lucide-react";

import { ConnectorIcon } from "@/components/connections/connector-icon";
import { Switch } from "@/components/builder/fields";
import { isInstagramServer } from "@/components/connections/instagram-sign-in-admin";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { vendorApi, ApiError, type MCPServerCounts, type VendorMCPServer } from "@/lib/api";
import { appLabel } from "@/lib/connectors";
import { cn } from "@/lib/utils";

export type AppState = "testing" | "ready" | "no_tools" | "not_tested";

/** Plain words for where a server stands. */
export function appState(s: VendorMCPServer, testing: boolean): AppState {
  if (testing) return "testing";
  if (s.status !== "VERIFIED") return "not_tested";
  return (s.bound_tools?.length ?? 0) > 0 ? "ready" : "no_tools";
}

export const STATE_LOOK: Record<AppState, { label: string; className: string }> = {
  testing: { label: "Testing…", className: "bg-indigo-50 text-indigo-700" },
  ready: { label: "Ready", className: "bg-emerald-50 text-emerald-700" },
  no_tools: { label: "No tools found", className: "bg-amber-50 text-amber-800" },
  not_tested: { label: "Needs a test", className: "bg-amber-50 text-amber-800" },
};

const RISK: Record<string, { label: string; className: string }> = {
  read: { label: "Reads", className: "bg-zinc-100 text-zinc-600" },
  edit: { label: "Changes data", className: "bg-amber-50 text-amber-800" },
  delete: { label: "Deletes", className: "bg-red-50 text-red-700" },
};

const runsWhere = (t: string) => (t === "stdio" ? "Runs on this platform" : t.includes("http") || t === "sse" ? "Remote server" : t);
const ago = (iso: string) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
};

type Tab = "overview" | "tools" | "access";

export function AppPanel({
  server,
  title,
  counts,
  accessToken,
  testing,
  onTest,
  onInstagram,
  onGrant,
  onClose,
}: {
  server: VendorMCPServer;
  /** Its title as the list shows it (told apart from a same-named app). */
  title?: string;
  counts?: MCPServerCounts;
  accessToken: string;
  testing: boolean;
  onTest: () => void;
  onInstagram: () => void;
  onGrant: () => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");
  const [asking, setAsking] = useState<"disconnect" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const label = { ...appLabel(server.name, server.description), ...(title ? { title } : {}) };
  const state = appState(server, testing);
  const look = STATE_LOOK[state];
  const detailsKey = ["vendor-mcp-details", server.id];
  const details = useQuery({ queryKey: detailsKey, queryFn: () => vendorApi.mcpDetails(accessToken, server.id), enabled: !!accessToken });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] });
    void queryClient.invalidateQueries({ queryKey: ["vendor-mcp-overview"] });
    void queryClient.invalidateQueries({ queryKey: detailsKey });
  };
  const fail = (err: unknown) => setError(err instanceof ApiError ? err.message : "Something went wrong.");

  const scope = useMutation({
    mutationFn: (isGlobal: boolean) => vendorApi.setMCPServerGlobal(accessToken, server.id, isGlobal),
    onSuccess: refresh,
    onError: fail,
  });
  const embed = useMutation({
    mutationFn: () => vendorApi.embedMCPServer(accessToken, server.id),
    onSuccess: () => {
      setNotice("Search index refreshed.");
      refresh();
    },
    onError: fail,
  });
  const disconnect = useMutation({
    mutationFn: () => vendorApi.disconnectMCPServer(accessToken, server.id),
    onSuccess: () => {
      setAsking(null);
      setNotice("Disconnected: your test credentials were cleared.");
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => vendorApi.deleteMCPServer(accessToken, server.id),
    onSuccess: () => {
      refresh();
      onClose();
    },
    onError: fail,
  });
  const toolsOff = useMutation({
    mutationFn: (names: string[]) => vendorApi.setDisabledTools(accessToken, server.id, names),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: detailsKey }),
    onError: fail,
  });
  const offNames = (details.data?.tools ?? []).filter((t) => !t.on).map((t) => t.name);
  const setOn = (name: string, on: boolean) => toolsOff.mutate(on ? offNames.filter((n) => n !== name) : [...offNames, name]);
  // Tools that sign in with a person's password (Instagram's "unofficial" tier): one click to turn them all off.
  const unofficial = (details.data?.tools ?? []).filter((t) => t.name.startsWith("unofficial_"));
  const unofficialOn = unofficial.filter((t) => t.on);

  const revoke = useMutation({
    mutationFn: (tenantId: string) => vendorApi.revokeGrant(accessToken, server.id, tenantId),
    onSuccess: refresh,
    onError: fail,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const d = details.data;
  const source = server.source_repo_url || server.server_url;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        className="flex h-full w-full flex-col border-l border-zinc-200 bg-[var(--surface-raised)] shadow-xl sm:w-[460px]"
        onClick={(e) => e.stopPropagation()}
        aria-label={`${label.title} settings`}
      >
        {/* Header */}
        <div className="flex items-start gap-3 border-b border-zinc-200 p-4">
          <ConnectorIcon name={server.name} size="sm" />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-zinc-900">{label.title}</h2>
            <p className="truncate text-xs text-zinc-500">{label.blurb || server.description || server.name}</p>
            <span className={cn("mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", look.className)}>
              {state === "testing" ? <Spinner className="h-3 w-3" /> : state === "ready" ? <CheckCircle2 className="h-3 w-3" /> : null}
              {look.label}
            </span>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-zinc-400 hover:text-zinc-700 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-zinc-200 px-4" role="tablist">
          {(["overview", "tools", "access"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn(
                "-mb-px border-b-2 px-2.5 py-2.5 text-sm font-medium capitalize cursor-pointer",
                tab === t ? "border-[var(--accent)] text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-800",
              )}
            >
              {t === "tools" ? `Tools${server.bound_tools?.length ? ` (${server.bound_tools.length})` : ""}` : t}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {error && <p className="rounded-md bg-red-50 p-2.5 text-xs text-red-700">{error}</p>}
          {notice && !error && <p className="rounded-md bg-emerald-50 p-2.5 text-xs text-emerald-800">{notice}</p>}

          {tab === "overview" && (
            <>
              {state !== "ready" && state !== "testing" && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  {state === "not_tested"
                    ? "Test it once: that checks it starts and finds its tools, so people can connect it."
                    : "It started but listed no tools. Test again, or check its credentials."}
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={onTest} disabled={testing}>
                  {testing ? <Spinner className="h-4 w-4" /> : <Wrench className="h-4 w-4" />} {state === "not_tested" ? "Test connection" : "Test again"}
                </Button>
                {isInstagramServer(server) && (
                  <Button type="button" size="sm" variant="outline" onClick={onInstagram}>
                    <Instagram className="h-4 w-4" /> Instagram sign-in
                  </Button>
                )}
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm">
                <Stat label="People connected" value={counts ? String(counts.users_connected) : "…"} />
                <Stat label="Tools" value={String(server.bound_tools?.length ?? 0)} />
                <Stat label="Who can use it" value={server.is_global ? "All users" : `${counts?.tenants_granted ?? 0} tenant${counts?.tenants_granted === 1 ? "" : "s"}`} />
                <Stat label="Last tested" value={d?.last_tested_at ? ago(d.last_tested_at) : d ? "Never" : "…"} />
              </dl>

              <div className="space-y-1 text-xs text-zinc-500">
                <p>
                  <span className="text-zinc-700">{runsWhere(server.transport)}</span> · name in the system: <code className="font-mono">{server.name}</code>
                </p>
                {source && (
                  <a href={source.startsWith("http") ? source : undefined} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-indigo-700 hover:underline">
                    <span className="truncate">{source}</span> {source.startsWith("http") && <ExternalLink className="h-3 w-3 shrink-0" />}
                  </a>
                )}
              </div>

              <div>
                <button type="button" disabled={embed.isPending} onClick={() => embed.mutate()} className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-600 hover:text-zinc-900 disabled:opacity-50 cursor-pointer">
                  {embed.isPending ? <Spinner className="h-3 w-3" /> : <RefreshCw className="h-3 w-3" />} Refresh search index
                </button>
                <p className="mt-0.5 text-xs text-zinc-400">Helps the AI builder find this app when someone describes a task. Do it after changing the description.</p>
              </div>

              {/* Danger zone */}
              <div className="space-y-3 rounded-lg border border-red-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-red-700">Danger zone</p>
                <Danger
                  icon={<Unlink className="h-4 w-4" />}
                  title="Disconnect"
                  text="Clears your test credentials. People's own connections stay."
                  confirm="Clear the test credentials?"
                  asking={asking === "disconnect"}
                  busy={disconnect.isPending}
                  disabled={server.status !== "VERIFIED"}
                  onAsk={() => setAsking("disconnect")}
                  onCancel={() => setAsking(null)}
                  onConfirm={() => disconnect.mutate()}
                />
                <Danger
                  icon={<Trash2 className="h-4 w-4" />}
                  title="Delete app"
                  text={`Removes it for everyone${counts?.users_connected ? `, including ${counts.users_connected} connected ${counts.users_connected === 1 ? "person" : "people"}` : ""}. Agents using it stop working.`}
                  confirm="Delete it for everyone?"
                  asking={asking === "delete"}
                  busy={remove.isPending}
                  onAsk={() => setAsking("delete")}
                  onCancel={() => setAsking(null)}
                  onConfirm={() => remove.mutate()}
                />
              </div>
            </>
          )}

          {tab === "tools" && (
            <div className="space-y-2">
              {details.isLoading && <div className="flex justify-center py-6"><Spinner className="h-5 w-5 text-zinc-400" /></div>}
              {d && d.tools.length === 0 && <p className="text-sm text-zinc-500">No tools yet. Test the connection to find them.</p>}
              {d && d.tools.length > 0 && (
                <>
                  <p className="text-xs text-zinc-500">
                    Agents ask the person first before any tool that changes or deletes data. A tool you turn off is never given to an agent.
                  </p>
                  {unofficialOn.length > 0 && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                      <p>
                        {unofficialOn.length} &ldquo;unofficial&rdquo; tool{unofficialOn.length === 1 ? "" : "s"} sign in with a person&apos;s password, which can get their account blocked.
                      </p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="mt-2 h-8"
                        disabled={toolsOff.isPending}
                        onClick={() => toolsOff.mutate([...new Set([...offNames, ...unofficial.map((t) => t.name)])])}
                      >
                        Turn them all off
                      </Button>
                    </div>
                  )}
                  {offNames.length > 0 && <p className="text-xs text-zinc-500">{offNames.length} turned off.</p>}
                  <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                    {d.tools.map((t) => {
                      const r = RISK[t.risk] ?? RISK.read;
                      return (
                        <li key={t.name} className={cn("px-3 py-2.5", !t.on && "opacity-60")}>
                          <div className="flex items-center gap-2">
                            <code className={cn("min-w-0 flex-1 truncate font-mono text-xs text-zinc-900", !t.on && "line-through")}>{t.name}</code>
                            <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs", r.className)}>{r.label}</span>
                            <Switch checked={t.on} label={t.on ? `Turn off ${t.name}` : `Turn on ${t.name}`} disabled={toolsOff.isPending} onChange={(v) => setOn(t.name, v)} />
                          </div>
                          {t.description && <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">{t.description}</p>}
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </div>
          )}

          {tab === "access" && (
            <div className="space-y-4">
              <div className="space-y-2">
                <p className="text-sm font-medium text-zinc-900">Who can use it</p>
                <ScopeOption
                  icon={<Globe className="h-4 w-4" />}
                  title="All users"
                  text="Everyone sees it on their Connectors page."
                  selected={server.is_global}
                  busy={scope.isPending && scope.variables === true}
                  onPick={() => !server.is_global && scope.mutate(true)}
                />
                <ScopeOption
                  icon={<Lock className="h-4 w-4" />}
                  title="Only some tenants"
                  text="Hidden until you give it to a tenant below."
                  selected={!server.is_global}
                  busy={scope.isPending && scope.variables === false}
                  onPick={() => server.is_global && scope.mutate(false)}
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-zinc-900">Tenants that have it</p>
                  <Button type="button" size="sm" variant="outline" onClick={onGrant}>
                    <Plus className="h-4 w-4" /> Give to a tenant
                  </Button>
                </div>
                {server.is_global && <p className="text-xs text-zinc-500">It&apos;s already open to all users, so these only matter if you restrict it.</p>}
                {d && d.grants.length === 0 && <p className="text-sm text-zinc-500">None yet.</p>}
                {d && d.grants.length > 0 && (
                  <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                    {d.grants.map((g) => (
                      <li key={g.tenant_id} className="flex items-center gap-2 px-3 py-2.5 text-sm">
                        <span className="min-w-0 flex-1 truncate text-zinc-900">{g.name}</span>
                        <button
                          type="button"
                          disabled={revoke.isPending && revoke.variables === g.tenant_id}
                          onClick={() => revoke.mutate(g.tenant_id)}
                          className="shrink-0 text-xs font-medium text-zinc-500 hover:text-red-600 disabled:opacity-50 cursor-pointer"
                        >
                          {revoke.isPending && revoke.variables === g.tenant_id ? "Removing…" : "Remove"}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-2.5">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-0.5 font-medium tabular-nums text-zinc-900">{value}</dd>
    </div>
  );
}

function ScopeOption({ icon, title, text, selected, busy, onPick }: { icon: React.ReactNode; title: string; text: string; selected: boolean; busy: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border p-3 text-left cursor-pointer",
        selected ? "border-[var(--accent)] bg-[var(--accent)]/5" : "border-zinc-200 hover:bg-zinc-50",
      )}
    >
      <span className={cn("mt-0.5", selected ? "text-[var(--accent)]" : "text-zinc-400")}>{busy ? <Spinner className="h-4 w-4" /> : icon}</span>
      <span>
        <span className="block text-sm font-medium text-zinc-900">{title}</span>
        <span className="block text-xs text-zinc-500">{text}</span>
      </span>
    </button>
  );
}

function Danger({
  icon, title, text, confirm, asking, busy, disabled, onAsk, onCancel, onConfirm,
}: {
  icon: React.ReactNode; title: string; text: string; confirm: string; asking: boolean; busy: boolean; disabled?: boolean;
  onAsk: () => void; onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span className="text-zinc-400">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-zinc-900">{title}</span>
        <span className="block text-xs text-zinc-500">{text}</span>
      </span>
      {asking ? (
        <span className="flex shrink-0 items-center gap-2 text-xs">
          <span className="text-zinc-600">{confirm}</span>
          <button type="button" disabled={busy} onClick={onConfirm} className="rounded-md bg-red-600 px-2 py-1 font-medium text-white hover:bg-red-700 disabled:opacity-50 cursor-pointer">
            {busy ? "…" : "Yes"}
          </button>
          <button type="button" onClick={onCancel} className="rounded-md px-2 py-1 text-zinc-500 hover:bg-zinc-100 cursor-pointer">No</button>
        </span>
      ) : (
        <Button type="button" size="sm" variant="outline" className="shrink-0 text-red-600" disabled={disabled} onClick={onAsk}>
          {title}
        </Button>
      )}
    </div>
  );
}
