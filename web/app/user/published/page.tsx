"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, Gauge, Globe, KeyRound, Network, Bot, Pause, Play, Timer, Trash2 } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { DailyBars } from "@/components/charts/daily-bars";
import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import { useAuthStore } from "@/stores/auth-store";


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
    <ProtectedDashboard path="/user" title="Published" description="Usage across everything you've published — public API keys and the embed widget.">
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
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
        <Tile Icon={KeyRound} label="Live keys" value={String(stats.live_keys)} />
        <Tile Icon={Activity} label="Total requests" value={stats.total_requests.toLocaleString()} sub={`last ${days} days`} />
        <Tile Icon={Gauge} label="Success rate" value={`${Math.round(stats.success_rate * 100)}%`} sub="of finished calls" />
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
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-100 text-[11px] uppercase tracking-wider text-zinc-500">
                  <th className="px-4 py-2 font-medium sm:px-5">Key</th>
                  <th className="px-3 py-2 font-medium">Publishes</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Requests ({days}d)</th>
                  <th className="px-3 py-2 text-right font-medium">Today</th>
                  <th className="px-3 py-2 font-medium">Last used</th>
                  <th className="px-4 py-2 sm:px-5"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {keys.map((k) => {
                  const busy = (toggle.isPending && toggle.variables?.id === k.id) || (revoke.isPending && revoke.variables === k.id);
                  return (
                    <tr key={k.id}>
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
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {(toggle.isError || revoke.isError) && <p className="px-5 pb-3 text-xs text-red-600">That didn&apos;t go through. Try again.</p>}
      </section>
    </div>
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
