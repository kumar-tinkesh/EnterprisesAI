"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Bot, ChevronDown, Globe, Network, Users } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { DailyBars } from "@/components/charts/daily-bars";
import { IconCopy, WAYS, wayOf } from "@/components/builder/publish-panel";
import { Menu } from "@/components/ui/menu";
import { Stat, Stats } from "@/components/ui/stats";
import { Spinner } from "@/components/ui/spinner";
import { builderApi, shareUrl } from "@/lib/builder/api";
import type { Published, Run, ShareCaller } from "@/lib/builder/types";
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
    <ProtectedDashboard path="/user" title="Published" description="Everything you've shared, and how it's being used.">
      <PublishedView />
    </ProtectedDashboard>
  );
}

function PublishedView() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const data = useQuery({ queryKey: ["published"], queryFn: () => builderApi.published(token, 14), enabled: !!token, refetchInterval: 30000 });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["published"] });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: "active" | "paused"; share?: boolean }) => builderApi.updatePublicKey(token, id, body),
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
      <div className="mt-6 flex flex-col items-center rounded-lg border border-dashed border-zinc-300 px-6 py-14 text-center">
        <Globe className="h-6 w-6 text-zinc-400" />
        <p className="mt-3 text-base font-semibold text-zinc-900">Nothing published yet</p>
        <p className="mt-1 max-w-sm text-sm text-zinc-500">Open an agent or workflow and press Publish to get a share link, a website chat or an API key.</p>
        <Link href="/user/executions" className="mt-5 inline-flex h-9 items-center rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white hover:bg-[var(--accent-hover)]">Open your agents</Link>
      </div>
    );
  }

  const latency = stats.avg_latency_ms >= 1000 ? `${(stats.avg_latency_ms / 1000).toFixed(1)} s` : `${stats.avg_latency_ms} ms`;

  return (
    <div className="mt-6 space-y-6">
      <Stats>
        <Stat label="Live" value={String(stats.live_keys)} sub={`of ${keys.length} published`} />
        <Stat label="Requests" value={stats.total_requests.toLocaleString()} sub={`last ${days} days`} />
        <Stat label="Success rate" value={`${Math.round(stats.success_rate * 100)}%`} sub={`avg ${latency} to answer`} />
        <Stat label="People" value={String(stats.people)} sub="used a share link" />
      </Stats>

      <DailyBars
        title="Usage"
        subtitle={`Requests a day, last ${days} days`}
        days={series.map((d) => ({ date: d.date, good: d.success, bad: d.error }))}
        empty="No requests yet."
      />

      <section className="space-y-3" aria-labelledby="keys-heading">
        <h2 id="keys-heading" className="text-base font-semibold text-zinc-900">
          Your published items <span className="font-normal text-zinc-500">· {keys.length}</span>
        </h2>
        {keys.length === 0 ? (
          <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-8 text-center text-sm text-zinc-500">
            Nothing live right now. Press <span className="font-medium text-zinc-900">Publish</span> on any agent or workflow.
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
            {keys.map((k) => (
              <KeyRow
                key={k.id}
                item={k}
                token={token}
                busy={(update.isPending && update.variables?.id === k.id) || (revoke.isPending && revoke.variables === k.id)}
                onUpdate={(body) => update.mutate({ id: k.id, ...body })}
                onRevoke={() => window.confirm(`Delete "${k.name}"? It stops working at once, everywhere it's used.`) && revoke.mutate(k.id)}
                onChange={refresh}
              />
            ))}
          </ul>
        )}
        {(update.isError || revoke.isError) && <p className="text-sm text-red-600">That didn&apos;t go through. Try again.</p>}
      </section>
    </div>
  );
}

/** One published item: what it is, what it runs, how it's doing, and a ⋯ menu for the rest. */
function KeyRow({
  item: k, token, busy, onUpdate, onRevoke, onChange,
}: {
  item: Published["keys"][number];
  token: string;
  busy: boolean;
  onUpdate: (body: { status?: "active" | "paused"; share?: boolean }) => void;
  onRevoke: () => void;
  onChange: () => void;
}) {
  const [people, setPeople] = useState(false);
  const way = WAYS.find((x) => x.way === wayOf(k))!;
  const active = k.status === "active";
  const url = k.share_enabled && k.share_slug ? shareUrl(k.share_slug) : null;

  return (
    <li className="px-4 py-3.5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-zinc-700"><way.Icon className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="font-medium text-zinc-900">{k.name}</span>
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", active ? "bg-emerald-50 text-emerald-700" : "bg-zinc-100 text-zinc-500")}>{active ? "Live" : "Paused"}</span>
            <span className="text-zinc-500">{way.title}</span>
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-zinc-500">
            <Link href={editHref(k.kind, k.target_id)} className="inline-flex max-w-[16rem] items-center gap-1 text-zinc-700 hover:text-zinc-900 hover:underline" title={`Open ${k.target_name}`}>
              {k.kind === "workflow" ? <Network className="h-3.5 w-3.5 shrink-0" /> : <Bot className="h-3.5 w-3.5 shrink-0" />}
              <span className="truncate">{k.target_name}</span>
            </Link>
            <span>· {k.version ? `v${k.version}` : "latest"}</span>
            <span>· {k.requests.toLocaleString()} requests</span>
            <span>· {k.runs_today}{k.daily_quota ? `/${k.daily_quota}` : ""} today</span>
            <span>· {k.last_used_at ? `used ${ago(k.last_used_at)}` : "never used"}</span>
          </p>
          {url && (
            <button
              type="button"
              onClick={() => setPeople((v) => !v)}
              aria-expanded={people}
              className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-zinc-700 hover:text-zinc-900 cursor-pointer"
            >
              <Users className="h-3.5 w-3.5" /> {k.people} {k.people === 1 ? "person" : "people"}
              <span className="font-normal text-zinc-500">· {k.tool_mode === "visitor" ? "their own accounts" : k.tool_mode === "mixed" ? "mixed accounts" : "your accounts"}</span>
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", people && "rotate-180")} />
            </button>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {busy && <Spinner className="h-4 w-4 text-zinc-400" />}
          {url && <IconCopy text={url} />}
          <Menu
            label={`More for ${k.name}`}
            items={[
              { label: active ? "Pause" : "Resume", onClick: () => onUpdate({ status: active ? "paused" : "active" }) },
              { label: k.share_enabled ? "Turn off share link" : "Turn on share link", onClick: () => onUpdate({ share: !k.share_enabled }) },
              { label: "Delete", onClick: onRevoke, danger: true },
            ]}
          />
        </div>
      </div>
      {people && (
        <div className="mt-3 ml-11 rounded-md bg-zinc-50 px-3 py-2">
          <Callers keyId={k.id} token={token} onChange={onChange} />
        </div>
      )}
    </li>
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
    <ul className="divide-y divide-zinc-100">
      {callers.data.map((c) => (
        <li key={c.user_id} className="py-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-zinc-900">
                {c.name || c.email || "Deleted account"}
                {c.blocked && <span className="ml-2 rounded-full bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700">Blocked</span>}
                {c.waiting > 0 && <span className="ml-2 rounded-full bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-700">{c.waiting} waiting for you</span>}
              </p>
              {c.name && c.email && <p className="truncate text-xs text-zinc-500">{c.email}</p>}
            </div>
            <span className="text-xs tabular-nums text-zinc-500">
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
              className="text-xs font-medium text-zinc-700 hover:text-zinc-900 disabled:opacity-40 cursor-pointer"
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
