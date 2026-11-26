"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, CircleSlash, Crosshair, Hand, Link2, Pencil, Send, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { JsonField, RiskBadge, Textarea } from "@/components/builder/fields";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import type { Approval, OutboundDraft } from "@/lib/builder/types";

export interface ApprovalCardProps {
  approval: Approval;
  token: string;
  onDone: () => void;
  /** Canvas step title (e.g. "Send WhatsApp Message") so users see which node paused. */
  stepLabel?: string;
  /** Canvas step type label (e.g. "Tool", "Approval"). */
  stepKind?: string;
  /** Focus/center that step on the canvas. */
  onLocate?: () => void;
}

/** Top banner showing exactly which workflow step/node paused for this approval. */
function StepOriginBar({
  approval,
  stepLabel,
  stepKind,
  onLocate,
}: {
  approval: Approval;
  stepLabel?: string;
  stepKind?: string;
  onLocate?: () => void;
}) {
  const p = approval.payload;
  const resolvedStep = stepLabel || p.step || (approval.run?.name && !p.server_name ? approval.run.name : undefined);
  const toolTag = approval.tool_name ? `${p.server_name ? `${p.server_name} · ` : ""}${approval.tool_name}` : p.server_name;
  if (!resolvedStep && !onLocate && !toolTag) return null;

  return (
    <div className="flex items-center justify-between gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 px-2.5 py-1.5 text-xs">
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-amber-400" aria-hidden />
        <span className="text-[11px] font-medium uppercase tracking-wide text-amber-300/90">Step</span>
        <span className="truncate font-semibold text-zinc-100">{resolvedStep ?? "Action required"}</span>
        {stepKind && (
          <span className="hidden rounded border border-white/10 bg-white/[0.06] px-1.5 py-0 text-[10px] text-zinc-300 sm:inline-block">
            {stepKind}
          </span>
        )}
        {toolTag && toolTag !== resolvedStep && (
          <span className="hidden truncate font-mono text-[10px] text-zinc-400 md:inline">({toolTag})</span>
        )}
      </div>
      {onLocate && (
        <button
          type="button"
          onClick={onLocate}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-400/30 bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-200 transition-colors hover:bg-amber-500/25 hover:text-white cursor-pointer"
          title="Highlight and jump to this node on the canvas"
        >
          <Crosshair className="h-3 w-3" />
          <span>Locate node</span>
        </button>
      )}
    </div>
  );
}

/** One decision a run is waiting on: approve, change, or say no. */
export function ApprovalCard({ approval, token, onDone, stepLabel, stepKind, onLocate }: ApprovalCardProps) {
  if (approval.kind === "tool_call" && approval.payload.outbound && approval.payload.draft) {
    return (
      <SendCard
        approval={approval}
        draft={approval.payload.draft}
        token={token}
        onDone={onDone}
        stepLabel={stepLabel}
        stepKind={stepKind}
        onLocate={onLocate}
      />
    );
  }
  return (
    <DecisionCard
      approval={approval}
      token={token}
      onDone={onDone}
      stepLabel={stepLabel}
      stepKind={stepKind}
      onLocate={onLocate}
    />
  );
}

function DecisionCard({ approval, token, onDone, stepLabel, stepKind, onLocate }: ApprovalCardProps) {
  const p = approval.payload;
  const [args, setArgs] = useState<Record<string, unknown> | null>(p.arguments ?? null);
  const [text, setText] = useState(p.text ?? "");
  const [missing, setMissing] = useState<Record<string, string>>({});
  const decide = useMutation({
    mutationFn: ({ decision, body }: { decision: "approve" | "reject" | "edit"; body?: Record<string, unknown> }) =>
      builderApi.decide(token, approval.id, decision, body),
    onSuccess: onDone,
  });
  const error =
    decide.error instanceof ApiError
      ? [decide.error.message, ...(((decide.error.body as { errors?: string[] })?.errors) ?? [])].join(" ")
      : decide.error
        ? "That didn't go through."
        : null;
  const busy = decide.isPending;

  return (
    <div className="space-y-2.5 rounded-2xl border border-amber-500/35 bg-[var(--surface-raised)] p-3.5 shadow-lg">
      <StepOriginBar approval={approval} stepLabel={stepLabel} stepKind={stepKind} onLocate={onLocate} />

      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-amber-500/30 bg-amber-500/15 text-amber-300">
          {approval.kind === "uncertain_call" ? <ShieldAlert className="h-3.5 w-3.5" /> : <Hand className="h-3.5 w-3.5" />}
        </span>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-100">
          {approval.kind === "human_step"
            ? stepLabel || `Approval: ${p.step ?? "review"}`
            : approval.kind === "missing_input"
              ? "Details needed"
              : `${p.server_name ? `${p.server_name} · ` : ""}${approval.tool_name}`}
        </p>
        {approval.risk && approval.kind !== "human_step" && <RiskBadge risk={approval.risk} />}
      </div>
      {approval.caller && (
        <p className="flex items-center gap-1 text-xs text-amber-200/90" title="This run came in through your share link and uses your connected tools.">
          <Link2 className="h-3 w-3 shrink-0" /> Via share link · {approval.caller.name || approval.caller.email || "a deleted account"}
          {approval.caller.name && approval.caller.email ? ` (${approval.caller.email})` : ""}
        </p>
      )}
      {p.message && <p className="text-xs leading-relaxed text-zinc-300">{p.message}</p>}

      {approval.kind === "tool_call" && (
        <>
          <p className="text-xs font-medium text-zinc-400">Arguments (you can adjust them before running)</p>
          <JsonField value={args} onChange={setArgs} rows={5} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide.mutate({ decision: "approve" })}>{p.outbound ? "Send" : "Approve"}</Button>
            <Button size="sm" variant="outline" disabled={busy || !args} onClick={() => decide.mutate({ decision: "edit", body: args ?? {} })}>
              {p.outbound ? "Send with my changes" : "Run with my changes"}
            </Button>
            <Button size="sm" variant="outline" className="text-red-400 hover:text-red-300" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>
              {p.outbound ? "Don't send" : "Don't run"}
            </Button>
          </div>
        </>
      )}

      {approval.kind === "uncertain_call" && (
        <>
          <pre className="max-h-32 overflow-auto rounded-lg border border-white/10 bg-zinc-950/70 p-2 font-mono text-xs text-zinc-200">{JSON.stringify(p.arguments ?? {}, null, 2)}</pre>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide.mutate({ decision: "approve" })}>It didn&apos;t run — run it again</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>It already ran — skip it</Button>
          </div>
        </>
      )}

      {approval.kind === "human_step" && (
        <>
          <Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide.mutate(text !== (p.text ?? "") ? { decision: "edit", body: { text } } : { decision: "approve" })}>
              {text !== (p.text ?? "") ? "Approve with my edits" : "Approve"}
            </Button>
            <Button size="sm" variant="outline" className="text-red-400 hover:text-red-300" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>Reject (stops the run)</Button>
          </div>
        </>
      )}

      {approval.kind === "missing_input" && (
        <>
          {(p.missing ?? []).map((field) => (
            <label key={field} className="block space-y-1">
              <span className="text-xs font-medium text-zinc-300">{field}</span>
              <Input className="h-8" value={missing[field] ?? ""} onChange={(e) => setMissing({ ...missing, [field]: e.target.value })} />
            </label>
          ))}
          {!!p.errors?.length && <p className="text-xs text-red-300">{p.errors.join("; ")}</p>}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={busy || (p.missing ?? []).some((f) => !(missing[f] ?? "").trim())}
              onClick={() => decide.mutate({ decision: "edit", body: missing })}
            >
              Continue
            </Button>
            <Button size="sm" variant="outline" className="text-red-400 hover:text-red-300" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>Stop the run</Button>
          </div>
        </>
      )}
      {busy && <Spinner className="h-4 w-4 text-amber-400" />}
      {error && <p className="text-xs text-red-300">{error}</p>}
    </div>
  );
}

/** A send tool waiting on a yes: the message it wrote first, then "send it?". A no keeps the
 *  message in the answer without sending it (builder.agents.runtime: _with_kept_drafts).
 *  Styled as part of the answer, in the app's own tokens — amber highlights the waiting step. */
function SendCard({
  approval,
  draft,
  token,
  onDone,
  stepLabel,
  stepKind,
  onLocate,
}: ApprovalCardProps & { draft: OutboundDraft }) {
  const p = approval.payload;
  const [body, setBody] = useState(draft.body);
  const [editing, setEditing] = useState(false);
  const [details, setDetails] = useState(false);
  const [decided, setDecided] = useState<"sent" | "kept" | null>(null);
  const changed = body !== draft.body;
  const decide = useMutation({
    mutationFn: ({ decision, body }: { decision: "approve" | "reject" | "edit"; body?: Record<string, unknown> }) =>
      builderApi.decide(token, approval.id, decision, body),
    onSuccess: (_data, { decision }) => {
      setDecided(decision === "reject" ? "kept" : "sent");
      onDone();
    },
  });
  const error =
    decide.error instanceof ApiError
      ? [decide.error.message, ...(((decide.error.body as { errors?: string[] })?.errors) ?? [])].join(" ")
      : decide.error
        ? "That didn't go through."
        : null;
  const busy = decide.isPending;
  const send = () =>
    decide.mutate(changed ? { decision: "edit", body: { ...(p.arguments ?? {}), [draft.body_field]: body } } : { decision: "approve" });

  if (decided) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
        {decided === "sent" ? (
          <><CheckCircle2 className="h-3.5 w-3.5 text-[var(--success)]" /> Sending{draft.to ? ` to ${draft.to}` : ""}…</>
        ) : (
          <><CircleSlash className="h-3.5 w-3.5" /> Not sent — kept in the reply</>
        )}
      </p>
    );
  }

  return (
    <div className="space-y-3 rounded-2xl border border-amber-500/35 bg-[var(--surface-raised)] p-3.5 shadow-lg">
      <StepOriginBar approval={approval} stepLabel={stepLabel} stepKind={stepKind} onLocate={onLocate} />

      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--accent-wash)]">
          <Send className="h-3.5 w-3.5 text-[var(--link)]" />
        </span>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--text)]">
          Ready to send{p.server_name ? <span className="font-normal text-[var(--text-muted)]"> · {p.server_name}</span> : null}
        </p>
        <span className="flex shrink-0 items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--warning)] animate-pulse" aria-hidden /> Waiting
        </span>
      </div>

      {approval.caller && (
        <p className="flex items-center gap-1 text-xs text-[var(--text-muted)]" title="This run came in through your share link and uses your connected tools.">
          <Link2 className="h-3 w-3 shrink-0" /> Via share link · {approval.caller.name || approval.caller.email || "a deleted account"}
          {approval.caller.name && approval.caller.email ? ` (${approval.caller.email})` : ""}
        </p>
      )}

      {(draft.to || draft.subject) && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {draft.to && (
            <span className="max-w-full truncate rounded-md border border-white/10 bg-[var(--surface-strong)] px-2 py-0.5 text-[var(--text-secondary)]">
              <span className="text-[var(--text-subtle)]">To</span> {draft.to}
            </span>
          )}
          {draft.subject && (
            <span className="max-w-full truncate rounded-md border border-white/10 bg-[var(--surface-strong)] px-2 py-0.5 text-[var(--text-secondary)]">
              <span className="text-[var(--text-subtle)]">Subject</span> {draft.subject}
            </span>
          )}
        </div>
      )}

      {editing ? (
        <textarea
          autoFocus
          rows={Math.min(14, Math.max(4, body.split("\n").length + 1))}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && body.trim() && !busy) send();
          }}
          aria-label="Message"
          className="w-full resize-y rounded-xl border border-[var(--border-strong)] bg-[var(--surface-strong)] px-3 py-2.5 text-sm leading-relaxed text-[var(--text)] outline-none focus:border-[var(--accent-border)]"
        />
      ) : (
        <div className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-white/5 bg-[var(--surface-strong)] px-3 py-2.5 text-sm leading-relaxed text-[var(--text-secondary)]">
          {body}
        </div>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Button size="sm" className="w-full sm:w-auto" disabled={busy || !body.trim()} onClick={send}>
          {busy && decide.variables?.decision !== "reject" ? <Spinner className="h-4 w-4" /> : <Send />}
          {changed ? "Send my version" : "Send"}
        </Button>
        <Button size="sm" variant="outline" className="w-full sm:w-auto" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>
          Don&apos;t send
        </Button>
        <div className="flex items-center justify-end gap-3 sm:ml-auto">
          <button
            type="button"
            onClick={() => setEditing((e) => !e)}
            className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)] cursor-pointer"
          >
            <Pencil className="h-3 w-3" /> {editing ? "Done editing" : "Edit"}
          </button>
          <button
            type="button"
            onClick={() => setDetails((d) => !d)}
            aria-expanded={details}
            className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)] cursor-pointer"
          >
            Details <ChevronDown className={`h-3 w-3 transition-transform ${details ? "rotate-180" : ""}`} />
          </button>
        </div>
      </div>
      {editing && <p className="text-xs text-[var(--text-subtle)]">⌘/Ctrl + Enter to send</p>}

      {details && (
        <div className="space-y-1.5">
          {p.message && <p className="text-xs text-[var(--text-muted)]">{p.message}</p>}
          <pre className="max-h-40 overflow-auto rounded-lg border border-white/10 bg-zinc-950/70 p-2.5 font-mono text-xs text-[var(--text-muted)]">
            {JSON.stringify(p.arguments ?? {}, null, 2)}
          </pre>
        </div>
      )}
      {error && <p className="text-xs text-[var(--danger)]">{error}</p>}
    </div>
  );
}
