"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Bot, Check, ChevronDown, Copy, ExternalLink, Eye, Globe, Monitor, Network, QrCode, Smartphone, Users, X } from "lucide-react";
import QRCodeLib from "qrcode";

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
  const [previewItem, setPreviewItem] = useState<Published["keys"][number] | null>(null);
  const data = useQuery({ queryKey: ["published"], queryFn: () => builderApi.published(token, 14), enabled: !!token, refetchInterval: 30000 });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["published"] });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: "active" | "paused"; share?: boolean; show_outline?: boolean }) => builderApi.updatePublicKey(token, id, body),
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
          <ul className="divide-y divide-white/5 rounded-lg border border-white/10 bg-[var(--surface)]">
            {keys.map((k) => (
              <KeyRow
                key={k.id}
                item={k}
                token={token}
                busy={(update.isPending && update.variables?.id === k.id) || (revoke.isPending && revoke.variables === k.id)}
                onUpdate={(body) => update.mutate({ id: k.id, ...body })}
                onRevoke={() => window.confirm(`Delete "${k.name}"? It stops working at once, everywhere it's used.`) && revoke.mutate(k.id)}
                onPreview={() => setPreviewItem(k)}
                onChange={refresh}
              />
            ))}
          </ul>
        )}
        {(update.isError || revoke.isError) && <p className="text-sm text-red-600">That didn&apos;t go through. Try again.</p>}
      </section>

      {previewItem && (
        <VisitorPreviewDialog item={previewItem} onClose={() => setPreviewItem(null)} />
      )}
    </div>
  );
}

/** One published item: what it is, what it runs, how it's doing, and a ⋯ menu for the rest. */
function KeyRow({
  item: k,
  token,
  busy,
  onUpdate,
  onRevoke,
  onPreview,
  onChange,
}: {
  item: Published["keys"][number];
  token: string;
  busy: boolean;
  onUpdate: (body: { status?: "active" | "paused"; share?: boolean; show_outline?: boolean }) => void;
  onRevoke: () => void;
  onPreview: () => void;
  onChange: () => void;
}) {
  const [people, setPeople] = useState(false);
  const way = WAYS.find((x) => x.way === wayOf(k))!;
  const active = k.status === "active";
  const url = k.share_enabled && k.share_slug ? shareUrl(k.share_slug) : null;

  return (
    <li className="px-4 py-3.5 transition-colors hover:bg-white/[0.02]">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] text-zinc-300">
          <way.Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="font-medium text-zinc-100">{k.name}</span>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium border",
                active
                  ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                  : "border-white/10 bg-white/[0.05] text-zinc-400"
              )}
            >
              {active && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden />}
              {active ? "Live" : "Paused"}
            </span>
            {k.name !== way.title && <span className="text-zinc-400">{way.title}</span>}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-400">
            <Link href={editHref(k.kind, k.target_id)} className="inline-flex max-w-[16rem] items-center gap-1 text-zinc-300 hover:text-white hover:underline" title={`Open ${k.target_name}`}>
              {k.kind === "workflow" ? <Network className="h-3.5 w-3.5 shrink-0 text-indigo-400" /> : <Bot className="h-3.5 w-3.5 shrink-0 text-indigo-400" />}
              <span className="truncate">{k.target_name}</span>
            </Link>
            <span>{k.version ? `v${k.version}` : "Latest version"}</span>
            <span>{k.requests.toLocaleString()} requests</span>
            <span>{k.runs_today}{k.daily_quota ? `/${k.daily_quota}` : ""} today</span>
            <span>{k.last_used_at ? `Used ${ago(k.last_used_at).toLowerCase()}` : "Never used"}</span>
          </p>
          {url && (
            <button
              type="button"
              onClick={() => setPeople((v) => !v)}
              aria-expanded={people}
              className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-zinc-300 hover:text-white cursor-pointer"
            >
              <Users className="h-3.5 w-3.5" /> {k.people} {k.people === 1 ? "person" : "people"}
              <span className="font-normal text-zinc-400">· {k.tool_mode === "visitor" ? "their own accounts" : k.tool_mode === "mixed" ? "mixed accounts" : "your accounts"}</span>
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", people && "rotate-180")} />
            </button>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {busy && <Spinner className="h-4 w-4 text-zinc-400" />}
          {url && (
            <button
              type="button"
              onClick={onPreview}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2.5 text-xs font-medium text-zinc-200 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors"
              title="Preview as visitor"
            >
              <Eye className="h-3.5 w-3.5" />
              <span>Preview</span>
            </button>
          )}
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors"
              title="Open public page in new tab"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          {url && <IconCopy text={url} />}
          <Menu
            label={`More for ${k.name}`}
            items={[
              ...(url ? [{ label: "Preview as visitor", onClick: onPreview }] : []),
              { label: active ? "Pause" : "Resume", onClick: () => onUpdate({ status: active ? "paused" : "active" }) },
              { label: k.share_enabled ? "Turn off share link" : "Turn on share link", onClick: () => onUpdate({ share: !k.share_enabled }) },
              ...(k.share_enabled ? [{ label: "Show how it works", checked: k.show_outline, onClick: () => onUpdate({ show_outline: !k.show_outline }) }] : []),
              { label: "Delete", onClick: onRevoke, danger: true },
            ]}
          />
        </div>
      </div>
      {people && (
        <div className="mt-3 ml-11 rounded-md border border-white/5 bg-white/[0.02] px-3 py-2">
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
                {c.waiting > 0 && <span className="ml-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium text-amber-300">{c.waiting} waiting for you</span>}
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
            <span className={cn("shrink-0", r.status === "failed" ? "text-red-400" : r.status === "waiting" ? "text-amber-400" : "text-zinc-400")}>{RUN_LABEL[r.status]}</span>
            <span className="shrink-0 text-zinc-500">{ago(r.created_at)}</span>
          </p>
          {r.output_text && <p className="line-clamp-2 text-zinc-500">{r.output_text}</p>}
        </li>
      ))}
    </ul>
  );
}

function VisitorPreviewDialog({
  item,
  onClose,
}: {
  item: Published["keys"][number];
  onClose: () => void;
}) {
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [showQr, setShowQr] = useState(false);
  const [copied, setCopied] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const url = item.share_slug ? shareUrl(item.share_slug) : "";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (showQr && canvasRef.current && url) {
      QRCodeLib.toCanvas(canvasRef.current, url, { width: 160, margin: 1 }, () => {});
    }
  }, [showQr, url]);

  const copy = () => {
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const active = item.status === "active";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-label={`Visitor Preview: ${item.name}`}
    >
      <div className="animate-fade-in fixed inset-0 bg-black/80 backdrop-blur-xs" onClick={onClose} />
      <div className="animate-scale-in relative flex flex-col h-[92vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-white/10 bg-[var(--surface-raised)] shadow-2xl">
        {/* Header bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5 min-w-0">
            <Globe className="h-4 w-4 shrink-0 text-indigo-400" />
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold text-zinc-100">
                Visitor Preview: {item.name}
              </h2>
              <p className="truncate text-xs text-zinc-400">
                {url}
              </p>
            </div>
          </div>

          {/* Device Toggle */}
          <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.04] p-0.5" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={device === "desktop"}
              onClick={() => setDevice("desktop")}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium cursor-pointer transition-colors",
                device === "desktop" ? "bg-white/[0.12] text-white shadow-xs" : "text-zinc-400 hover:text-white"
              )}
            >
              <Monitor className="h-3.5 w-3.5" /> Desktop
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={device === "mobile"}
              onClick={() => setDevice("mobile")}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium cursor-pointer transition-colors",
                device === "mobile" ? "bg-white/[0.12] text-white shadow-xs" : "text-zinc-400 hover:text-white"
              )}
            >
              <Smartphone className="h-3.5 w-3.5" /> Mobile
            </button>
          </div>

          {/* Quick actions */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setShowQr((v) => !v)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-xs font-medium transition-colors cursor-pointer",
                showQr ? "bg-white/[0.12] text-white" : "bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08] hover:text-white"
              )}
              title="Show QR Code for phone"
            >
              <QrCode className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">QR Code</span>
            </button>
            <button
              type="button"
              onClick={copy}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2.5 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white cursor-pointer transition-colors"
              title="Copy public link"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              <span className="hidden sm:inline">{copied ? "Copied" : "Copy"}</span>
            </button>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-2.5 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 hover:text-indigo-200 cursor-pointer transition-colors"
              title="Open public page in new tab"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Open Live</span>
            </a>
            <button
              type="button"
              onClick={onClose}
              className="ml-1 rounded-md p-1.5 text-zinc-400 hover:bg-white/[0.06] hover:text-white cursor-pointer transition-colors"
              aria-label="Close preview"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Info badges row */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 bg-white/[0.02] px-4 py-2 sm:px-6 text-xs text-zinc-400">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium border", active ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400" : "border-white/10 bg-white/[0.05] text-zinc-400")}>
              <span className={cn("h-1.5 w-1.5 rounded-full", active ? "bg-emerald-400" : "bg-zinc-500")} />
              {active ? "Live" : "Paused"}
            </span>
            <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[11px] text-zinc-300">
              {item.tool_mode === "visitor" ? "👤 Visitors connect own accounts" : item.tool_mode === "mixed" ? "🔀 Mixed accounts" : "🔑 Runs on your connected accounts"}
            </span>
            {item.share_enabled && (
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[11px] text-zinc-300">
                {item.show_outline ? "📋 Workflow outline shown" : "🔒 Workflow outline hidden"}
              </span>
            )}
          </div>
          <span className="text-[11px] text-zinc-400">
            Interactive guest preview
          </span>
        </div>

        {/* Content View / Frame */}
        <div className="relative flex-1 overflow-auto bg-[var(--bg)] p-4 flex items-center justify-center">
          {showQr && (
            <div className="animate-scale-in absolute top-4 right-4 z-20 flex flex-col items-center rounded-xl border border-white/10 bg-[var(--surface-raised)] p-4 shadow-2xl">
              <p className="text-xs font-medium text-zinc-200 mb-2">Scan with Phone</p>
              <div className="rounded-lg bg-white p-2">
                <canvas ref={canvasRef} />
              </div>
              <p className="mt-2 text-[10px] text-zinc-400 max-w-[160px] text-center truncate">{url}</p>
            </div>
          )}

          {device === "desktop" ? (
            <div key="desktop" className="animate-scale-in h-full w-full rounded-xl border border-white/10 bg-[var(--surface)] shadow-xl overflow-hidden flex flex-col">
              <div className="flex items-center gap-1.5 border-b border-white/10 bg-white/[0.03] px-3 py-2">
                <div className="flex gap-1.5">
                  <div className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
                  <div className="h-2.5 w-2.5 rounded-full bg-amber-500/80" />
                  <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/80" />
                </div>
                <div className="mx-auto flex h-6 max-w-sm flex-1 items-center justify-center rounded-md border border-white/10 bg-black/30 px-3 text-[11px] text-zinc-400 truncate">
                  {url}
                </div>
              </div>
              <iframe
                src={url}
                className="h-full w-full flex-1 border-0 bg-transparent"
                title={`Desktop Preview - ${item.name}`}
              />
            </div>
          ) : (
            <div key="mobile" className="animate-scale-in relative flex flex-col h-full max-h-[720px] w-[375px] rounded-[40px] border-[10px] border-zinc-800 bg-black shadow-2xl overflow-hidden ring-1 ring-white/10">
              {/* Dynamic Island */}
              <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10 flex h-4 w-24 items-center justify-center rounded-full bg-zinc-900">
                <div className="h-2 w-2 rounded-full bg-zinc-800 mr-2" />
                <div className="h-1.5 w-8 rounded-full bg-zinc-800" />
              </div>
              <iframe
                src={url}
                className="h-full w-full flex-1 pt-6 border-0 bg-transparent"
                title={`Mobile Preview - ${item.name}`}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
