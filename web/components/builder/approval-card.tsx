"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Hand, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { JsonField, RiskBadge, Textarea } from "@/components/builder/fields";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import type { Approval } from "@/lib/builder/types";

/** One decision a run is waiting on: approve, change, or say no. */
export function ApprovalCard({ approval, token, onDone }: { approval: Approval; token: string; onDone: () => void }) {
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
    <div className="space-y-2 rounded-xl border border-amber-300 bg-amber-50/60 p-3">
      <div className="flex items-center gap-2">
        {approval.kind === "uncertain_call" ? <ShieldAlert className="h-4 w-4 text-amber-700" /> : <Hand className="h-4 w-4 text-amber-700" />}
        <p className="flex-1 text-sm font-semibold text-amber-900">
          {approval.kind === "human_step" ? `Approval: ${p.step ?? "review"}` : approval.kind === "missing_input" ? "Details needed" : `${p.server_name ?? ""}.${approval.tool_name}`}
        </p>
        {approval.risk && approval.kind !== "human_step" && <RiskBadge risk={approval.risk} />}
      </div>
      {p.message && <p className="text-xs text-amber-900">{p.message}</p>}

      {approval.kind === "tool_call" && (
        <>
          <p className="text-[11px] font-medium text-zinc-600">Arguments (you can change them)</p>
          <JsonField value={args} onChange={setArgs} rows={5} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide.mutate({ decision: "approve" })}>Approve</Button>
            <Button size="sm" variant="outline" disabled={busy || !args} onClick={() => decide.mutate({ decision: "edit", body: args ?? {} })}>Run with my changes</Button>
            <Button size="sm" variant="outline" className="text-red-600" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>Don&apos;t run</Button>
          </div>
        </>
      )}

      {approval.kind === "uncertain_call" && (
        <>
          <pre className="max-h-32 overflow-auto rounded bg-white p-2 text-[11px] text-zinc-700">{JSON.stringify(p.arguments ?? {}, null, 2)}</pre>
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
            <Button size="sm" variant="outline" className="text-red-600" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>Reject (stops the run)</Button>
          </div>
        </>
      )}

      {approval.kind === "missing_input" && (
        <>
          {(p.missing ?? []).map((field) => (
            <label key={field} className="block space-y-1">
              <span className="text-xs font-medium text-zinc-700">{field}</span>
              <Input className="h-8" value={missing[field] ?? ""} onChange={(e) => setMissing({ ...missing, [field]: e.target.value })} />
            </label>
          ))}
          {!!p.errors?.length && <p className="text-xs text-red-700">{p.errors.join("; ")}</p>}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={busy || (p.missing ?? []).some((f) => !(missing[f] ?? "").trim())}
              onClick={() => decide.mutate({ decision: "edit", body: missing })}
            >
              Continue
            </Button>
            <Button size="sm" variant="outline" className="text-red-600" disabled={busy} onClick={() => decide.mutate({ decision: "reject" })}>Stop the run</Button>
          </div>
        </>
      )}
      {busy && <Spinner className="h-4 w-4 text-amber-700" />}
      {error && <p className="text-xs text-red-700">{error}</p>}
    </div>
  );
}
