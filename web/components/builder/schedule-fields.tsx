"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CheckCircle2, Pause, Play, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Section, Select, Textarea, Toggle } from "@/components/builder/fields";
import { builderApi, browserTimezone } from "@/lib/builder/api";
import {
  COMMON_TIMEZONES,
  DEFAULT_CRON,
  REPEAT_LABELS,
  WEEKDAYS,
  buildCron,
  formatRunTime,
  parseCron,
  type Repeat,
  type SchedulePreset,
} from "@/lib/builder/schedule";
import type { Schedule, TriggerSchedule, WorkflowNode } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** Repeats / time / day pickers (or a raw cron), a timezone, and a live "next runs" preview. */
export function SchedulePicker({
  cron,
  timezone,
  token,
  disabled,
  onChange,
}: {
  cron: string;
  timezone: string;
  token: string;
  disabled?: boolean;
  onChange: (value: { cron: string; timezone: string }) => void;
}) {
  const [preset, setPreset] = useState<SchedulePreset>(() => parseCron(cron));
  // Follow outside changes (an AI edit, a reload) unless they're our own.
  useEffect(() => {
    if (buildCron(preset) !== cron) setPreset(parseCron(cron));
  }, [cron]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch: Partial<SchedulePreset>) => {
    const next = { ...preset, ...patch };
    if (patch.repeat === "custom") next.cron = buildCron(preset);
    setPreset(next);
    onChange({ cron: buildCron(next), timezone });
  };

  const [checked, setChecked] = useState({ cron, timezone });
  useEffect(() => {
    const t = setTimeout(() => setChecked({ cron, timezone }), 350);
    return () => clearTimeout(t);
  }, [cron, timezone]);
  const preview = useQuery({
    queryKey: ["schedule-preview", checked.cron, checked.timezone],
    queryFn: () => builderApi.previewSchedule(token, checked.cron, checked.timezone),
    enabled: !!token && !!checked.cron.trim(),
    staleTime: 60_000,
  });
  const mine = browserTimezone();

  return (
    <div className="space-y-3">
      <Field label="Repeats">
        <Select value={preset.repeat} disabled={disabled} onChange={(e) => set({ repeat: e.target.value as Repeat })}>
          {(Object.keys(REPEAT_LABELS) as Repeat[]).map((r) => (
            <option key={r} value={r}>{REPEAT_LABELS[r]}</option>
          ))}
        </Select>
      </Field>
      {preset.repeat === "weekly" && (
        <Field label="On">
          <Select value={preset.weekday} disabled={disabled} onChange={(e) => set({ weekday: Number(e.target.value) })}>
            {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </Select>
        </Field>
      )}
      {preset.repeat === "monthly" && (
        <Field label="On day" hint="1–28, so it runs every month.">
          <Input className="h-9" type="number" min={1} max={28} value={preset.day} disabled={disabled} onChange={(e) => set({ day: Number(e.target.value) || 1 })} />
        </Field>
      )}
      {preset.repeat === "hours" && (
        <Field label="Every how many hours">
          <Input className="h-9" type="number" min={1} max={23} value={preset.every} disabled={disabled} onChange={(e) => set({ every: Number(e.target.value) || 1 })} />
        </Field>
      )}
      {["daily", "weekdays", "weekly", "monthly"].includes(preset.repeat) && (
        <Field label="At">
          <Input className="h-9" type="time" value={preset.time} disabled={disabled} onChange={(e) => set({ time: e.target.value })} />
        </Field>
      )}
      {preset.repeat === "custom" && (
        <Field label="Cron" hint="minute hour day month weekday — e.g. 30 8 * * 1-5">
          <Input className="h-9 font-mono" value={preset.cron} disabled={disabled} onChange={(e) => set({ cron: e.target.value })} />
        </Field>
      )}
      <Field label="Timezone">
        <div className="flex gap-2">
          <Input
            className="h-9"
            list="builder-timezones"
            value={timezone}
            disabled={disabled}
            onChange={(e) => onChange({ cron, timezone: e.target.value })}
          />
          {timezone !== mine && !disabled && (
            <Button type="button" size="sm" variant="outline" className="h-9 shrink-0" onClick={() => onChange({ cron, timezone: mine })}>
              Use mine
            </Button>
          )}
        </div>
        <datalist id="builder-timezones">
          {Array.from(new Set([mine, ...COMMON_TIMEZONES])).map((z) => <option key={z} value={z} />)}
        </datalist>
      </Field>
      <div className="rounded-lg bg-zinc-50 px-3 py-2 text-xs">
        {preview.isFetching && !preview.data ? (
          <Spinner className="h-3.5 w-3.5 text-zinc-400" />
        ) : preview.data?.ok ? (
          <>
            <p className="font-medium text-zinc-800">{preview.data.description}</p>
            <p className="mt-0.5 text-zinc-500">Next: {preview.data.next_runs.map((t) => formatRunTime(t, timezone)).join(" · ")}</p>
          </>
        ) : preview.data ? (
          <p className="flex gap-1 text-red-600"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{preview.data.error}</p>
        ) : (
          <p className="text-zinc-400">Pick when it runs.</p>
        )}
      </div>
    </div>
  );
}

/** Where a saved schedule stands: next time, and how the last one went. */
export function ScheduleStatus({ schedule }: { schedule: Schedule }) {
  return (
    <div className="space-y-1 text-xs">
      <p className={cn("flex items-center gap-1.5 font-medium", schedule.enabled ? "text-emerald-700" : "text-zinc-500")}>
        <CalendarClock className="h-3.5 w-3.5" />
        {schedule.enabled && schedule.next_run_at ? `Next run ${formatRunTime(schedule.next_run_at, schedule.timezone)}` : "Paused"}
      </p>
      {schedule.last_run_at && (
        <p className={cn("flex gap-1.5", schedule.last_status === "started" ? "text-zinc-500" : "text-amber-700")}>
          {schedule.last_status === "started" ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />}
          <span>
            Last {formatRunTime(schedule.last_run_at, schedule.timezone)}
            {schedule.last_status === "started" ? " — started a run" : `: ${schedule.last_error ?? schedule.last_status}`}
          </span>
        </p>
      )}
    </div>
  );
}

/** The Schedule trigger step of a workflow: edited here, applied when the workflow is saved. */
export function WorkflowScheduleFields({
  node,
  token,
  workflowId,
  readOnly,
  onChange,
}: {
  node: WorkflowNode;
  token: string;
  workflowId: string;
  readOnly?: boolean;
  onChange: (patch: Partial<WorkflowNode>) => void;
}) {
  const sched: TriggerSchedule = node.schedule ?? {};
  const set = (patch: Partial<TriggerSchedule>) => onChange({ schedule: { ...sched, ...patch } });
  const saved = useQuery({
    queryKey: ["builder-schedules", "workflow", workflowId],
    queryFn: () => builderApi.listSchedules(token, { workflow_id: workflowId }),
    enabled: !!token && !!workflowId,
  });
  const current = (saved.data ?? []).find((s) => s.node_id === node.id);

  return (
    <Section title="Schedule">
      <Toggle checked={sched.enabled !== false} label="Run automatically" onChange={(v) => set({ enabled: v })} />
      <SchedulePicker
        cron={sched.cron ?? ""}
        timezone={sched.timezone ?? browserTimezone()}
        token={token}
        disabled={readOnly}
        onChange={(v) => set({ cron: v.cron, timezone: v.timezone })}
      />
      {!sched.cron && (
        <Button type="button" size="sm" variant="outline" disabled={readOnly} onClick={() => set({ cron: DEFAULT_CRON, timezone: sched.timezone ?? browserTimezone() })}>
          <CalendarClock /> Set a schedule
        </Button>
      )}
      <Field label="Each run is asked" hint="The request every scheduled run starts with.">
        <Textarea rows={3} value={sched.input ?? ""} disabled={readOnly} placeholder="Summarize yesterday's unread email" onChange={(e) => set({ input: e.target.value })} />
      </Field>
      <div className="rounded-lg border border-zinc-200 p-3">
        {current ? <ScheduleStatus schedule={current} /> : <p className="text-xs text-zinc-500">Not scheduled yet — save the workflow to turn it on.</p>}
        <p className="mt-1.5 text-[11px] text-zinc-400">Runs as the workflow&apos;s creator, with their connected tools. Changes apply when you save.</p>
      </div>
    </Section>
  );
}

/** An agent's schedules: list, add, pause, run now, delete. */
export function AgentSchedules({ agentId, token }: { agentId: string; token: string }) {
  const queryClient = useQueryClient();
  const key = ["builder-schedules", "agent", agentId];
  const list = useQuery({ queryKey: key, queryFn: () => builderApi.listSchedules(token, { agent_id: agentId }), enabled: !!token });
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ cron: DEFAULT_CRON, timezone: browserTimezone(), input: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong.");

  const create = useMutation({
    mutationFn: () => builderApi.createSchedule(token, { agent_id: agentId, ...draft }),
    onSuccess: () => {
      setAdding(false);
      setDraft({ cron: DEFAULT_CRON, timezone: browserTimezone(), input: "" });
      setError(null);
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
      setNotice("Started — see it under Earlier runs in the playground.");
      void refresh();
      void queryClient.invalidateQueries({ queryKey: ["builder-runs", "agent", agentId] });
    },
    onError: fail,
  });

  return (
    <Section
      title={`Schedules (${list.data?.length ?? 0})`}
      action={
        !adding && (
          <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer">
            <Plus className="h-3 w-3" /> Add
          </button>
        )
      }
    >
      {error && <p className="text-xs text-red-600">{error}</p>}
      {notice && <p className="text-xs text-emerald-700">{notice}</p>}
      {(list.data ?? []).map((s) => (
        <div key={s.id} className="space-y-2 rounded-lg border border-zinc-200 p-3">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-zinc-900">{s.description}</p>
              <p className="truncate text-xs text-zinc-500">{s.timezone} · “{s.input.text || "—"}”</p>
            </div>
            {s.editable && (
              <div className="flex shrink-0 gap-1">
                <button type="button" title="Run now" aria-label="Run now" disabled={runNow.isPending} onClick={() => runNow.mutate(s)} className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-indigo-600 cursor-pointer">
                  <Play className="h-3.5 w-3.5" />
                </button>
                <button type="button" title={s.enabled ? "Pause" : "Resume"} aria-label={s.enabled ? "Pause" : "Resume"} onClick={() => toggle.mutate(s)} className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 cursor-pointer">
                  {s.enabled ? <Pause className="h-3.5 w-3.5" /> : <CalendarClock className="h-3.5 w-3.5" />}
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
            )}
          </div>
          <ScheduleStatus schedule={s} />
          {!s.is_mine && <p className="text-[11px] text-zinc-400">Set by a teammate; runs with their connected tools.</p>}
        </div>
      ))}
      {list.data?.length === 0 && !adding && <p className="text-xs text-zinc-400">Not scheduled. Add one to run this agent automatically.</p>}
      {adding && (
        <div className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/30 p-3">
          <SchedulePicker cron={draft.cron} timezone={draft.timezone} token={token} onChange={(v) => setDraft({ ...draft, ...v })} />
          <Field label="Each run asks the agent">
            <Textarea rows={2} value={draft.input} placeholder="Check my inbox and draft replies to anything urgent" onChange={(e) => setDraft({ ...draft, input: e.target.value })} />
          </Field>
          <p className="text-[11px] text-zinc-500">Runs as you, with your connected tools. Tools that change data still wait for your approval.</p>
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={create.isPending || !draft.input.trim()} onClick={() => create.mutate()}>
              {create.isPending ? <Spinner className="h-4 w-4" /> : <CalendarClock />} Schedule it
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </div>
      )}
    </Section>
  );
}
