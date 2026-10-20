"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Ban, CheckCircle2, ChevronDown, Gauge, Globe, KeyRound, Link2, Network, Bot, Pause, Play, Timer, Trash2, Users } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { DailyBars } from "@/components/charts/daily-bars";
import { Spinner } from "@/components/ui/spinner";
import { builderApi, shareUrl } from "@/lib/builder/api";
import type { Run, ShareCaller } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";


const editHref = (kind: "agent" | "workflow", id: string) => `/user/executions?chat=${kind}:${encodeURIComponent(id)}&edit=1`;

function ago(iso: string | null): string {
  if (!iso) return "Never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}


export default function PublishedPage() {
  return (
    <ProtectedDashboard path="/user" title="Published" description="Usage across everything you've published — share links, public API keys and the embed widget.">
      <PublishedView />
    </ProtectedDashboard>
  );
}

function PublishedView() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const data = useQuery({ queryKey: ["published"], queryFn: () => builderApi.published(token, 14), enabled: !!token, refetchInterval: 30000 });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["published"] });
  const toggle = useMutation({
    mutationFn: (k: { id: string; status: string }) => builderApi.updatePublicKey(token, k.id, { status: k.status === "active" ? "paused" : "active" }),
    onSuccess: refresh,
  });
  const revoke = useMutation({ mutationFn: (id: string) => builderApi.revokePublicKey(token, id), onSuccess: refresh });
  const share = useMutation({
    mutationFn: (k: { id: string; share: boolean }) => builderApi.updatePublicKey(token, k.id, { share: k.share }),
    onSuccess: refresh,
  });
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const copy = (id: string, slug: string) => {
    void navigator.clipboard?.writeText(shareUrl(slug));
    setCopied(id);
    setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500);
  };

  if (data.isLoading) return <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-zinc-400" /></div>;
  if (data.isError || !data.data) {
    return <p className="mt-6 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">Couldn&apos;t load what you&apos;ve published. Refresh to try again.</p>;
  }
  const { stats, series, keys, days } = data.data;

  // Nothing published and nothing ever called: one empty state, not four zeros and an empty chart.
  if (keys.length === 0 && stats.total_requests === 0) {
    return (
      <div className="mt-6 flex flex-col items-center rounded-xl border border-dashed border-zinc-300 bg-white px-6 py-12 text-center">
        <Globe className="h-7 w-7 text-zinc-400" />
        <p className="mt-3 text-sm font-medium text-zinc-900">Nothing published yet</p>
        <p className="mt-1 max-w-sm text-xs text-zinc-500">Open an agent or workflow on the canvas and press Publish to get an API key and an embed widget.</p>
        <Link href="/user/executions" className="mt-4 text-sm font-medium text-indigo-600 hover:text-indigo-800">Open your agents</Link>
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5 lg:gap-4">
        <Tile Icon={KeyRound} label="Live keys" value={String(stats.live_keys)} />
        <Tile Icon={Activity} label="Total requests" value={stats.total_requests.toLocaleString()} sub={`last ${days} days`} />
        <Tile Icon={Gauge} label="Success rate" value={`${Math.round(stats.success_rate * 100)}%`} sub="of finished calls" />
        <Tile Icon={Users} label="People" value={String(stats.people)} sub={`used a share link, last ${days} days`} />
        <Tile Icon={Timer} label="Avg latency" value={stats.avg_latency_ms >= 1000 ? `${(stats.avg_latency_ms / 1000).toFixed(1)} s` : `${stats.avg_latency_ms} ms`} sub="start to answer" />
      </div>

      <DailyBars
        title="Public API calls"
        subtitle={`Last ${days} days, API and embed widget`}
        days={series.map((d) => ({ date: d.date, good: d.success, bad: d.error }))}
        empty="No public calls recorded yet. Publish an agent or workflow to get started."
      />

      <section className="rounded-xl border border-zinc-200 bg-white" aria-labelledby="keys-heading">
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 sm:px-5">
          <h2 id="keys-heading" className="font-semibold text-zinc-900">Publishable keys</h2>
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600">{keys.length} key{keys.length === 1 ? "" : "s"}</span>
        </div>
        {keys.length === 0 ? (
          <div className="flex flex-col items-center px-6 py-10 text-center">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100"><Globe className="h-5 w-5 text-zinc-400" /></span>
            <p className="mt-3 text-sm text-zinc-500">Nothing published yet. Click <span className="font-medium text-zinc-700">Publish</span> on any agent or workflow.</p>
            <Link href="/user/executions" className="mt-3 text-sm font-medium text-indigo-600 hover:text-indigo-800">Open your agents</Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-100 text-[11px] uppercase tracking-wider text-zinc-500">
                  <th className="px-4 py-2 font-medium sm:px-5">Key</th>
                  <th className="px-3 py-2 font-medium">Publishes</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Share link</th>
                  <th className="px-3 py-2 text-right font-medium">Requests ({days}d)</th>
                  <th className="px-3 py-2 text-right font-medium">Today</th>
                  <th className="px-3 py-2 font-medium">Last used</th>
                  <th className="px-4 py-2 sm:px-5"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {keys.map((k) => {
                  const busy =
                    (toggle.isPending && toggle.variables?.id === k.id) || (revoke.isPending && revoke.variables === k.id) || (share.isPending && share.variables?.id === k.id);
                  return (
                    <Fragment key={k.id}>
                    <tr>
                      <td className="px-4 py-3 sm:px-5">
                        <p className="font-medium text-zinc-900">{k.name}</p>
                        <p className="font-mono text-[11px] text-zinc-500">{k.key_prefix}…</p>
                      </td>
                      <td className="px-3 py-3">
                        <Link href={editHref(k.kind, k.target_id)} className="inline-flex max-w-[14rem] items-center gap-1.5 text-zinc-700 hover:text-indigo-600" title={`Open ${k.target_name}`}>
                          {k.kind === "workflow" ? <Network className="h-3.5 w-3.5 shrink-0 text-zinc-400" /> : <Bot className="h-3.5 w-3.5 shrink-0 text-zinc-400" />}
                          <span className="truncate">{k.target_name}</span>
                        </Link>
                        <p className="text-[11px] text-zinc-500">{k.version ? `Pinned to v${k.version}` : "Latest saved version"}</p>
                      </td>
                      <td className="px-3 py-3">
                        {k.status === "active" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700"><CheckCircle2 className="h-3 w-3" /> Live</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700"><Pause className="h-3 w-3" /> Paused</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        {k.share_enabled && k.share_slug ? (
                          <div className="flex flex-col items-start gap-1">
                            <button type="button" onClick={() => copy(k.id, k.share_slug!)} className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer" title={shareUrl(k.share_slug)}>
                              <Link2 className="h-3.5 w-3.5" /> {copied === k.id ? "Copied" : "Copy link"}
                            </button>
                            <span className="text-[11px] text-zinc-500">{k.tool_mode === "visitor" ? "Their own apps" : k.tool_mode === "mixed" ? "Mixed apps" : "Your apps"}</span>
                            <button
                              type="button"
                              onClick={() => setOpen(open === k.id ? null : k.id)}
                              aria-expanded={open === k.id}
                              className="inline-flex items-center gap-0.5 text-[11px] text-zinc-500 hover:text-zinc-900 cursor-pointer"
                            >
                              {k.people} {k.people === 1 ? "person" : "people"} <ChevronDown className={cn("h-3 w-3 transition-transform", open === k.id && "rotate-180")} />
                            </button>
                          </div>
                        ) : (
                          <span className="text-xs text-zinc-400">Off</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-zinc-900">{k.requests.toLocaleString()}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-zinc-700">
                        {k.runs_today}
                        {k.daily_quota ? <span className="text-zinc-500"> / {k.daily_quota}</span> : null}
                      </td>
                      <td className="px-3 py-3 text-xs text-zinc-500">{ago(k.last_used_at)}</td>
                      <td className="px-4 py-3 sm:px-5">
                        <div className="flex justify-end gap-1">
                          {busy && <Spinner className="h-4 w-4 self-center text-zinc-400" />}
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => share.mutate({ id: k.id, share: !k.share_enabled })}
                            title={k.share_enabled ? "Turn the share link off" : "Make a share link: anyone can use it after signing in"}
                            aria-label={k.share_enabled ? `Turn off the share link of ${k.name}` : `Make a share link for ${k.name}`}
                            aria-pressed={k.share_enabled}
                            className={cn("rounded-md p-1.5 hover:bg-zinc-100 disabled:opacity-50 cursor-pointer", k.share_enabled ? "text-indigo-600" : "text-zinc-500 hover:text-zinc-900")}
                          >
                            <Link2 className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => toggle.mutate({ id: k.id, status: k.status })}
                            title={k.status === "active" ? "Pause: callers get an error until you resume it" : "Resume"}
                            aria-label={k.status === "active" ? `Pause ${k.name}` : `Resume ${k.name}`}
                            className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50 cursor-pointer"
                          >
                            {k.status === "active" ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => window.confirm(`Revoke "${k.name}"? It stops working at once, everywhere it's used.`) && revoke.mutate(k.id)}
                            title="Revoke"
                            aria-label={`Revoke ${k.name}`}
                            className="rounded-md p-1.5 text-zinc-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 cursor-pointer"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {open === k.id && (
                      <tr>
                        <td colSpan={8} className="bg-zinc-50 px-4 py-3 sm:px-5">
                          <Callers keyId={k.id} token={token} onChange={refresh} />
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {(toggle.isError || revoke.isError || share.isError) && <p className="px-5 pb-3 text-xs text-red-600">That didn&apos;t go through. Try again.</p>}
      </section>
    </div>
  );
}

/** Who ran a key from its share link — with your tools — and how much; block someone, or see what they asked. */
function Callers({ keyId, token, onChange }: { keyId: string; token: string; onChange: () => void }) {
  const queryClient = useQueryClient();
  const [shown, setShown] = useState<string | null>(null);
  const callers = useQuery({ queryKey: ["share-callers", keyId], queryFn: () => builderApi.listCallers(token, keyId), enabled: !!token, refetchInterval: 30000 });
  const block = useMutation({
    mutationFn: (c: ShareCaller) => builderApi.setCallerBlocked(token, keyId, c.user_id, !c.blocked),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["share-callers", keyId] });
      onChange();
    },
  });

  if (callers.isLoading) return <Spinner className="h-4 w-4 text-zinc-400" />;
  if (callers.isError) return <p className="text-xs text-red-600">Couldn&apos;t load who used it.</p>;
  if (!callers.data?.length) return <p className="text-xs text-zinc-500">Nobody has used the link yet. Copy it and send it to someone.</p>;
  return (
    <ul className="divide-y divide-zinc-200">
      {callers.data.map((c) => (
        <li key={c.user_id} className="py-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-zinc-900">
                {c.name || c.email || "Deleted account"}
                {c.blocked && <span className="ml-2 rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">Blocked</span>}
                {c.waiting > 0 && <span className="ml-2 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">{c.waiting} waiting for you</span>}
              </p>
              {c.name && c.email && <p className="truncate text-[11px] text-zinc-500">{c.email}</p>}
            </div>
            <span className="text-[11px] tabular-nums text-zinc-500">
              {c.runs} run{c.runs === 1 ? "" : "s"} · {c.runs_today} today{c.failed ? ` · ${c.failed} failed` : ""} · {ago(c.last_run_at)}
              {c.private_runs > 0 && (
                <span title="Runs with their own connected apps: what they asked and got stays theirs."> · {c.private_runs} with their own apps</span>
              )}
            </span>
            <button
              type="button"
              onClick={() => setShown(shown === c.user_id ? null : c.user_id)}
              aria-expanded={shown === c.user_id}
              disabled={c.runs - c.private_runs === 0}
              className="text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-40 cursor-pointer"
            >
              {shown === c.user_id ? "Hide runs" : "Runs"}
            </button>
            <button
              type="button"
              disabled={block.isPending && block.variables?.user_id === c.user_id}
              onClick={() => (c.blocked || window.confirm(`Block ${c.name || c.email}? They won't be able to start new runs from this link.`)) && block.mutate(c)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs disabled:opacity-50 cursor-pointer",
                c.blocked ? "border-zinc-200 text-zinc-700 hover:text-zinc-900" : "border-red-200 text-red-600 hover:bg-red-50",
              )}
            >
              <Ban className="h-3 w-3" /> {c.blocked ? "Unblock" : "Block"}
            </button>
          </div>
          {shown === c.user_id && <CallerRuns keyId={keyId} userId={c.user_id} token={token} />}
        </li>
      ))}
      {block.isError && <li className="py-2 text-xs text-red-600">That didn&apos;t go through. Try again.</li>}
    </ul>
  );
}

const RUN_LABEL: Record<Run["status"], string> = {
  queued: "Queued", running: "Running", waiting: "Waiting for you", succeeded: "Done", failed: "Failed", cancelled: "Cancelled",
};

function CallerRuns({ keyId, userId, token }: { keyId: string; userId: string; token: string }) {
  const runs = useQuery({ queryKey: ["share-caller-runs", keyId, userId], queryFn: () => builderApi.callerRuns(token, keyId, userId), enabled: !!token });
  if (runs.isLoading) return <Spinner className="mt-2 h-4 w-4 text-zinc-400" />;
  return (
    <ul className="mt-2 space-y-1.5 border-l-2 border-zinc-200 pl-3">
      {(runs.data ?? []).map((r) => (
        <li key={r.id} className="text-xs">
          <p className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate font-medium text-zinc-800">{r.input?.text || "(no message)"}</span>
            <span className={cn("shrink-0", r.status === "failed" ? "text-red-600" : r.status === "waiting" ? "text-amber-700" : "text-zinc-500")}>{RUN_LABEL[r.status]}</span>
            <span className="shrink-0 text-zinc-500">{ago(r.created_at)}</span>
          </p>
          {r.output_text && <p className="line-clamp-2 text-zinc-500">{r.output_text}</p>}
        </li>
      ))}
    </ul>
  );
}

function Tile({ Icon, label, value, sub }: { Icon: typeof Globe; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 sm:p-5">
      <div className="flex items-center gap-2 text-zinc-500">
        <Icon className="h-4 w-4" />
        <span className="text-xs font-medium sm:text-sm">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-bold tabular-nums text-zinc-900 sm:text-3xl">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-zinc-500">{sub}</p>}
    </div>
  );
}
