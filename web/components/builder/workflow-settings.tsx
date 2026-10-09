"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, Edit3, Eye, FileText, Settings2, ShieldCheck, Trash2, Upload, X, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/builder/fields";
import { knowledgeApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import type { ApprovalOverride, WorkflowConfig } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

type Tab = "execution" | "governance" | "knowledge";

const selectCls = "w-full rounded-xl border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-xs text-zinc-900 focus:border-indigo-400 focus:outline-none";

/** Whole-run settings, in Marketplace's three tabs. Changes are part of the workflow (Save applies them). */
export function WorkflowSettings({
  workflowId,
  config,
  token,
  canManage,
  onChange,
  onClose,
}: {
  workflowId: string;
  config: WorkflowConfig;
  token: string;
  canManage: boolean;
  onChange: (next: WorkflowConfig) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("execution");
  const set = (patch: Partial<WorkflowConfig>) => onChange({ ...config, ...patch });
  const tabs: { id: Tab; label: string; Icon: typeof Zap; tone: string }[] = [
    { id: "execution", label: "Execution & Policy", Icon: Zap, tone: "text-amber-400" },
    { id: "governance", label: "Governance & KB", Icon: ShieldCheck, tone: "text-emerald-400" },
    { id: "knowledge", label: "Knowledge", Icon: BookOpen, tone: "text-sky-400" },
  ];

  return (
    <div className="flex max-h-full flex-col">
      <div className="mb-3 flex items-center justify-between border-b border-zinc-200 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-indigo-400 bg-indigo-50 text-indigo-600"><Settings2 className="h-4 w-4" /></span>
          <span className="text-xs font-semibold text-zinc-900">Workflow Settings</span>
        </div>
        <button type="button" aria-label="Close settings" onClick={onClose} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"><X className="h-4 w-4" /></button>
      </div>

      <div className="mb-3 flex gap-1 rounded-xl border border-zinc-200 bg-zinc-50 p-1 text-xs" role="tablist">
        {tabs.map(({ id, label, Icon, tone }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 font-medium cursor-pointer",
              tab === id ? "border border-indigo-400 bg-indigo-50 text-indigo-600" : "text-zinc-500 hover:text-zinc-900",
            )}
          >
            <Icon className={cn("h-3.5 w-3.5", tab === id ? tone : "text-zinc-400")} /> {label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <fieldset disabled={!canManage} className="contents">
          {tab === "execution" && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2.5">
                <label className="block">
                  <span className="mb-1 block text-[11px] font-medium text-zinc-600">Max run time</span>
                  <select className={selectCls} value={config.max_run_seconds ?? ""} onChange={(e) => set({ max_run_seconds: e.target.value ? Number(e.target.value) : null })}>
                    <option value="">No limit (Default)</option>
                    <option value={60}>1 minute</option>
                    <option value={180}>3 minutes</option>
                    <option value={300}>5 minutes</option>
                    <option value={600}>10 minutes</option>
                    <option value={1800}>30 minutes</option>
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-[11px] font-medium text-zinc-600">If a step fails</span>
                  <select
                    className={selectCls}
                    value={config.on_node_failure ?? "abort"}
                    onChange={(e) => {
                      const v = e.target.value as WorkflowConfig["on_node_failure"];
                      set({ on_node_failure: v, node_retry_count: v === "retry" ? config.node_retry_count || 2 : config.node_retry_count });
                    }}
                  >
                    <option value="abort">Stop run (Default)</option>
                    <option value="skip">Skip &amp; continue</option>
                    <option value="retry">Retry step</option>
                  </select>
                </label>
              </div>
              {config.on_node_failure === "retry" && (
                <div className="grid grid-cols-2 gap-2 rounded-xl border border-zinc-200 bg-zinc-50 p-2.5">
                  <label className="block">
                    <span className="mb-1 block text-[10.5px] font-medium text-zinc-500">Attempts</span>
                    <select className={selectCls} value={config.node_retry_count || 2} onChange={(e) => set({ node_retry_count: Number(e.target.value) })}>
                      {[1, 2, 3, 5].map((n) => <option key={n} value={n}>{n} {n === 1 ? "time" : "times"}</option>)}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[10.5px] font-medium text-zinc-500">If still failing</span>
                    <select className={selectCls} value={config.node_retry_fallback ?? "abort"} onChange={(e) => set({ node_retry_fallback: e.target.value as "abort" | "skip" })}>
                      <option value="abort">Stop run</option>
                      <option value="skip">Skip step</option>
                    </select>
                  </label>
                </div>
              )}
              <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 p-2.5">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-indigo-600" checked={!!config.include_step_summary} onChange={(e) => set({ include_step_summary: e.target.checked })} />
                <span>
                  <span className="block text-xs font-medium text-zinc-900">Include step-by-step summary</span>
                  <span className="block text-[10.5px] text-zinc-500">Appends individual step outputs to final answer.</span>
                </span>
              </label>
            </div>
          )}

          {tab === "governance" && <Governance config={config} token={token} set={set} />}
        </fieldset>
        {tab === "knowledge" && <OwnKnowledge workflowId={workflowId} config={config} token={token} canManage={canManage} set={set} />}
      </div>
    </div>
  );
}

function Governance({ config, token, set }: { config: WorkflowConfig; token: string; set: (p: Partial<WorkflowConfig>) => void }) {
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });
  const selected = config.default_knowledge_base_ids ?? [];
  const overrides = config.approval_overrides ?? {};
  const shared = (kbs.data ?? []).filter((k) => k.id !== config.own_knowledge_base_id);
  return (
    <div className="space-y-3">
      <div>
        <span className="mb-1 block text-[11px] font-medium text-zinc-600">Default Knowledge Base</span>
        <p className="mb-1.5 text-[10.5px] text-zinc-500">Every agent step searches these, on top of its own.</p>
        {kbs.isLoading ? (
          <Spinner className="h-4 w-4 text-zinc-400" />
        ) : shared.length === 0 ? (
          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-2.5 text-center text-xs text-zinc-500">No knowledge bases in workspace yet.</div>
        ) : (
          <div className="max-h-32 space-y-1 overflow-y-auto rounded-xl border border-zinc-200 bg-zinc-50 p-2 text-xs">
            {shared.map((k) => {
              const on = selected.includes(k.id);
              return (
                <label key={k.id} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-zinc-900 hover:bg-zinc-100">
                  <input type="checkbox" className="h-3.5 w-3.5 accent-indigo-600" checked={on}
                    onChange={() => set({ default_knowledge_base_ids: on ? selected.filter((x) => x !== k.id) : [...selected, k.id] })} />
                  <span className="truncate font-medium">{k.name}</span>
                </label>
              );
            })}
          </div>
        )}
      </div>
      <div>
        <span className="mb-1 block text-[11px] font-medium text-zinc-600">Approval Overrides (this workflow)</span>
        <p className="mb-1.5 text-[10.5px] text-zinc-500">Ask before tools run — Default leaves it to each step&apos;s agent.</p>
        <div className="grid grid-cols-3 gap-2">
          {([["read", "Reads", Eye], ["edit", "Writes", Edit3], ["delete", "Deletes", Trash2]] as const).map(([kind, label, Icon]) => (
            <label key={kind} className="flex flex-col gap-1 rounded-xl border border-zinc-200 bg-zinc-50 p-2">
              <span className="flex items-center gap-1 text-[10.5px] font-medium text-zinc-500"><Icon className="h-3 w-3" /> {label}</span>
              <select
                className={selectCls}
                aria-label={`Approval for ${label}`}
                value={overrides[kind] ?? "default"}
                onChange={(e) => set({ approval_overrides: { ...overrides, [kind]: e.target.value as ApprovalOverride } })}
              >
                <option value="default">Default</option>
                <option value="always">Always</option>
                <option value="never">Never</option>
              </select>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Settings -> Knowledge: this workflow's OWN knowledge base (made on first use, deleted with the workflow). */
function OwnKnowledge({
  workflowId,
  config,
  token,
  canManage,
  set,
}: {
  workflowId: string;
  config: WorkflowConfig;
  token: string;
  canManage: boolean;
  set: (p: Partial<WorkflowConfig>) => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const kbId = config.own_knowledge_base_id ?? null;
  const docsKey = ["knowledge-documents", kbId];
  const docs = useQuery({
    queryKey: docsKey,
    queryFn: () => knowledgeApi.listDocuments(token, kbId!),
    enabled: !!token && !!kbId,
    refetchInterval: (q) => ((q.state.data as { status: string }[] | undefined)?.some((d) => d.status === "processing") ? 3000 : false),
  });
  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong.");

  const ensure = async (): Promise<string> => {
    if (kbId) return kbId;
    const r = await builderApi.createWorkflowKnowledge(token, workflowId);
    set({ own_knowledge_base_id: r.knowledge_base_id });
    return r.knowledge_base_id;
  };
  const refresh = (id: string) => queryClient.invalidateQueries({ queryKey: ["knowledge-documents", id] });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const id = await ensure();
      for (const f of files) await knowledgeApi.uploadDocument(token, id, f);
      return id;
    },
    onSuccess: (id) => { setError(null); void refresh(id); },
    onError: fail,
  });
  const paste = useMutation({
    mutationFn: async () => {
      const id = await ensure();
      await knowledgeApi.addText(token, id, { title: title.trim() || "Note", content: text });
      return id;
    },
    onSuccess: (id) => { setTitle(""); setText(""); setError(null); void refresh(id); },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (docId: string) => knowledgeApi.removeDocument(token, kbId!, docId),
    onSuccess: () => void refresh(kbId!),
    onError: fail,
  });

  return (
    <div className="space-y-3 text-xs">
      <p className="text-zinc-500">
        What this workflow knows: every agent step searches it when it runs. It isn&apos;t shared with other workflows and is deleted with this one.
      </p>
      {!kbId && <p className="rounded-lg bg-zinc-50 p-2.5 text-zinc-500">Nothing yet — add a file or some text.</p>}
      <ul className="space-y-1">
        {(docs.data ?? []).map((d) => (
          <li key={d.id} className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1.5">
            <FileText className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
            <span className="min-w-0 flex-1 truncate text-zinc-900">{d.filename}</span>
            {d.status === "processing" ? <Spinner className="h-3.5 w-3.5 text-zinc-400" /> : d.status === "ready" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> : <span className="text-red-600" title={d.error_message ?? ""}>failed</span>}
            {canManage && (
              <button type="button" aria-label={`Remove ${d.filename}`} onClick={() => remove.mutate(d.id)} className="text-zinc-400 hover:text-red-600 cursor-pointer"><Trash2 className="h-3.5 w-3.5" /></button>
            )}
          </li>
        ))}
      </ul>
      {canManage && (
        <>
          <input ref={fileRef} type="file" multiple hidden accept=".pdf,.txt,.md,.csv,.xlsx,.docx,.jpg,.jpeg,.png"
            onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ""; if (files.length) upload.mutate(files); }} />
          <Button size="sm" variant="outline" className="h-8" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
            {upload.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Upload />} Upload files
          </Button>
          <div className="space-y-1.5 rounded-xl border border-zinc-200 p-2.5">
            <Input className="h-8 text-xs" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Textarea rows={3} placeholder="Paste text: prices, policies, FAQs…" value={text} onChange={(e) => setText(e.target.value)} />
            <Button size="sm" className="h-8" disabled={paste.isPending || !text.trim()} onClick={() => paste.mutate()}>
              {paste.isPending ? <Spinner className="h-3.5 w-3.5" /> : null} Add text
            </Button>
          </div>
        </>
      )}
      {error && <p className="text-red-600">{error}</p>}
    </div>
  );
}
