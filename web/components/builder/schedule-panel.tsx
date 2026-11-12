"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Paperclip, Pencil, Play, Plus, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { FileChip } from "@/components/builder/chat/chat-message";
import { Field, Select, Switch, Textarea } from "@/components/builder/fields";
import { coerce } from "@/components/builder/playground";
import { SchedulePicker, ScheduleStatus } from "@/components/builder/schedule-fields";
import { builderApi, browserTimezone } from "@/lib/builder/api";
import { inputFields } from "@/lib/builder/graph";
import { DEFAULT_CRON, describeSchedule } from "@/lib/builder/schedule";
import type { InputVariable, Schedule, WorkflowNode } from "@/lib/builder/types";

const MAX_FILES = 5;
type File_ = { id: string; filename: string; kind: "document" | "image" };
type Draft = { cron: string; timezone: string; input: string; values: Record<string, string>; files: File_[] };

const asText = (v: unknown) => (v === undefined || v === null ? "" : typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v));

function blank(): Draft {
  return { cron: DEFAULT_CRON, timezone: browserTimezone(), input: "", values: {}, files: [] };
}

function fromSchedule(s: Schedule): Draft {
  const values: Record<string, string> = {};
  for (const [k, v] of Object.entries(s.input.variables ?? {})) values[k] = asText(v);
  return { cron: s.cron, timezone: s.timezone, input: s.input.text ?? "", values, files: s.input.attachments ?? [] };
}

/** The form for one schedule: when, what it's asked, its inputs and files (same for every run). */
function ScheduleForm({
  initial,
  fields,
  token,
  saving,
  onSave,
  onCancel,
}: {
  initial: Draft;
  fields: InputVariable[];
  token: string;
  saving: boolean;
  onSave: (d: Draft) => void;
  onCancel: () => void;
}) {
  const [d, setD] = useState<Draft>(initial);
  const [uploading, setUploading] = useState(0);
  const [fileError, setFileError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const missing = fields.filter((f) => f.required && !(d.values[f.name] ?? "").trim());

  const attach = async (list: FileList | null) => {
    setFileError(null);
    const chosen = Array.from(list ?? []).slice(0, Math.max(0, MAX_FILES - d.files.length));
    for (const file of chosen) {
      setUploading((n) => n + 1);
      try {
        const up = await builderApi.uploadAttachment(token, file);
        setD((cur) => ({ ...cur, files: [...cur.files, { id: up.id, filename: up.filename, kind: up.kind }] }));
      } catch (err) {
        setFileError(err instanceof Error ? `${file.name}: ${err.message}` : `Couldn't attach ${file.name}.`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  };

  return (
    <div className="space-y-4 rounded-xl border border-indigo-200 bg-indigo-50/30 p-3">
      <SchedulePicker cron={d.cron} timezone={d.timezone} token={token} onChange={(v) => setD({ ...d, ...v })} />

      {fields.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-medium text-zinc-700">Inputs for every run</p>
          {fields.map((f) => (
            <Field key={f.name} label={`${f.label || f.name}${f.required ? " *" : ""}`} hint={f.type === "boolean" ? undefined : f.description ?? undefined}>
              {f.type === "boolean" ? (
                <Select value={d.values[f.name] ?? ""} onChange={(e) => setD({ ...d, values: { ...d.values, [f.name]: e.target.value } })}>
                  <option value="">—</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </Select>
              ) : (
                <Input
                  className="h-9"
                  type={f.type === "number" ? "number" : "text"}
                  value={d.values[f.name] ?? ""}
                  onChange={(e) => setD({ ...d, values: { ...d.values, [f.name]: e.target.value } })}
                />
              )}
            </Field>
          ))}
        </div>
      )}

      <Field label="Files for every run" hint="e.g. your resume. Kept with the schedule; each run reads it.">
        <div className="flex flex-wrap items-center gap-1.5">
          {d.files.map((f) => (
            <FileChip key={f.id} file={f} onRemove={() => setD({ ...d, files: d.files.filter((x) => x.id !== f.id) })} />
          ))}
          {uploading > 0 && <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500"><Spinner className="h-3 w-3" /> Reading…</span>}
          {d.files.length < MAX_FILES && (
            <Button type="button" size="sm" variant="outline" className="h-7" onClick={() => picker.current?.click()}>
              <Paperclip className="h-3.5 w-3.5" /> Attach
            </Button>
          )}
          <input ref={picker} type="file" multiple hidden onChange={(e) => { void attach(e.target.files); e.target.value = ""; }} />
        </div>
        {fileError && <p className="mt-1 text-xs text-red-600">{fileError}</p>}
      </Field>

      <Field label="Message for each run" hint={fields.length ? "Optional, the inputs above are usually enough." : "What every run is asked."}>
        <Textarea rows={2} value={d.input} placeholder="Find today's best matches" onChange={(e) => setD({ ...d, input: e.target.value })} />
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={saving || uploading > 0 || missing.length > 0 || !d.cron} onClick={() => onSave(d)}>
          {saving ? <Spinner className="h-4 w-4" /> : <CalendarClock />} Save schedule
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>Cancel</Button>
        {missing.length > 0 && <span className="self-center text-xs text-amber-700">Fill in {missing.map((f) => f.label || f.name).join(", ")} first</span>}
      </div>
    </div>
  );
}

/** A workflow's schedules: turn on or off, pick the time, and the inputs/files every run gets. */
export function WorkflowSchedulePanel({
  workflowId,
  nodes,
  token,
  dirty,
  onOpenStep,
  onClose,
}: {
  workflowId: string;
  nodes: WorkflowNode[];
  token: string;
  dirty: boolean;
  onOpenStep: (nodeId: string) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const key = ["builder-schedules", "workflow", workflowId];
  const list = useQuery({ queryKey: key, queryFn: () => builderApi.listSchedules(token, { workflow_id: workflowId }), enabled: !!token });
  const fields = inputFields(nodes);
  const stepTrigger = nodes.find((n) => n.type === "schedule_trigger");
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong.");

  const body = (d: Draft) => {
    const variables: Record<string, unknown> = {};
    for (const f of fields) {
      const v = coerce(f, (d.values[f.name] ?? "").trim());
      if (v !== undefined) variables[f.name] = v;
    }
    return { cron: d.cron, timezone: d.timezone, input: d.input, variables, attachment_ids: d.files.map((f) => f.id) };
  };
  const save = useMutation({
    mutationFn: (d: Draft) =>
      editing === "new" || editing === null
        ? builderApi.createSchedule(token, { workflow_id: workflowId, ...body(d) })
        : builderApi.updateSchedule(token, editing, body(d)),
    onSuccess: () => {
      setEditing(null);
      setError(null);
      setNotice(null);
      void refresh();
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (s: Schedule) => builderApi.updateSchedule(token, s.id, { enabled: !s.enabled }),
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (s: Schedule) => builderApi.deleteSchedule(token, s.id),
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const runNow = useMutation({
    mutationFn: (s: Schedule) => builderApi.runSchedule(token, s.id),
    onSuccess: () => {
      setNotice("Started. It's in the workflow's chat history and on Executions.");
      void refresh();
    },
    onError: fail,
  });

  const rows = list.data ?? [];
  const mine = rows.filter((s) => s.editable);
  const others = rows.filter((s) => !s.editable && !s.node_id);
  const fromStep = rows.filter((s) => s.node_id);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3">
        <CalendarClock className="h-4 w-4 text-sky-600" />
        <h2 className="flex-1 text-sm font-semibold text-zinc-900">Schedule</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <p className="text-xs text-zinc-500">
          Runs by itself at the time you pick, as you, with your connected apps. Steps that change data still wait for your OK.
        </p>
        {dirty && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">You have unsaved changes. Scheduled runs use the saved workflow.</p>}
        {error && <p className="text-xs text-red-600">{error}</p>}
        {notice && <p className="text-xs text-emerald-700">{notice}</p>}
        {list.isLoading && <div className="flex justify-center py-6"><Spinner className="h-5 w-5 text-zinc-400" /></div>}

        {stepTrigger && (
          <div className="space-y-2 rounded-xl border border-zinc-200 p-3">
            <p className="text-sm font-medium text-zinc-900">{describeSchedule(stepTrigger.schedule)}</p>
            {fromStep.map((s) => <ScheduleStatus key={s.id} schedule={s} />)}
            <p className="text-xs text-zinc-500">This workflow starts on its Schedule step. Change the time and the on/off switch there.</p>
            <Button type="button" size="sm" variant="outline" onClick={() => onOpenStep(stepTrigger.id)}>Open the Schedule step</Button>
          </div>
        )}

        {!stepTrigger && mine.map((s) =>
          editing === s.id ? (
            <ScheduleForm key={s.id} initial={fromSchedule(s)} fields={fields} token={token} saving={save.isPending} onSave={(d) => save.mutate(d)} onCancel={() => setEditing(null)} />
          ) : (
            <div key={s.id} className="space-y-2 rounded-xl border border-zinc-200 p-3">
              <div className="flex items-start gap-3">
                <Switch checked={s.enabled} label={s.enabled ? "On: click to turn off" : "Off: click to turn on"} disabled={toggle.isPending} onChange={() => toggle.mutate(s)} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-zinc-900">{s.description}</p>
                  <p className="truncate text-xs text-zinc-500">
                    {s.timezone}
                    {s.input.attachments?.length ? ` · ${s.input.attachments.map((a) => a.filename).join(", ")}` : ""}
                    {Object.keys(s.input.variables ?? {}).length ? ` · ${Object.keys(s.input.variables ?? {}).length} inputs set` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 gap-0.5">
                  <button type="button" title="Run now" aria-label="Run now" disabled={runNow.isPending} onClick={() => runNow.mutate(s)} className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-indigo-600 cursor-pointer">
                    <Play className="h-3.5 w-3.5" />
                  </button>
                  <button type="button" title="Change" aria-label="Change schedule" onClick={() => { setEditing(s.id); setError(null); }} className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 cursor-pointer">
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Delete"
                    aria-label="Delete schedule"
                    onClick={() => window.confirm("Delete this schedule?") && remove.mutate(s)}
                    className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-red-600 cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <ScheduleStatus schedule={s} />
            </div>
          ),
        )}

        {others.map((s) => (
          <div key={s.id} className="space-y-1 rounded-xl border border-zinc-200 p-3">
            <p className="text-sm font-medium text-zinc-900">{s.description}</p>
            <ScheduleStatus schedule={s} />
            <p className="text-xs text-zinc-400">Set by a teammate; runs with their connected apps.</p>
          </div>
        ))}

        {!stepTrigger && editing === "new" && (
          <ScheduleForm initial={blank()} fields={fields} token={token} saving={save.isPending} onSave={(d) => save.mutate(d)} onCancel={() => setEditing(null)} />
        )}
        {!stepTrigger && editing === null && list.isSuccess && (
          <Button type="button" size="sm" variant={mine.length ? "outline" : "default"} onClick={() => { setEditing("new"); setError(null); }}>
            <Plus /> {mine.length ? "Add another time" : "Schedule it"}
          </Button>
        )}
        {!stepTrigger && list.isSuccess && mine.length === 0 && editing === null && (
          <p className="text-xs text-zinc-400">Not scheduled. Pick a time, like every day at 9:00, and it runs by itself.</p>
        )}
      </div>
    </div>
  );
}
