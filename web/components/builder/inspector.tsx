"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Plus, Trash2, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { AgentStepConfig } from "@/components/builder/agent-step-config";
import { NODE_LOOK } from "@/components/builder/flow-node";
import { OutputSettings } from "@/components/builder/output-settings";
import { Field, JsonField, RiskBadge, Section, Select, Textarea, Toggle } from "@/components/builder/fields";
import { WorkflowScheduleFields } from "@/components/builder/schedule-fields";
import { ToolPicker } from "@/components/builder/tool-picker";
import { builderApi, browserTimezone } from "@/lib/builder/api";
import { DEFAULT_CRON } from "@/lib/builder/schedule";
import { cn } from "@/lib/utils";
import { NODE_META, isTrigger, serverIdOf, toolName } from "@/lib/builder/graph";
import type {
  Agent,
  ConditionRule,
  InputVariable,
  Problem,
  WorkflowEdge,
  WorkflowNode,
} from "@/lib/builder/types";

const RULE_OPS = ["contains", "not_contains", "equals", "not_equals", "starts_with", "ends_with", "gt", "gte", "lt", "lte", "is_empty", "is_not_empty"];

function Problems({ problems }: { problems: Problem[] }) {
  if (!problems.length) return null;
  return (
    <div className="space-y-1 border-b border-red-100 bg-red-50 px-3.5 py-2.5">
      {problems.map((p, i) => (
        <p key={i} className="flex gap-1.5 text-xs text-red-700">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {p.message}
        </p>
      ))}
    </div>
  );
}

function PanelHeader({
  title,
  subtitle,
  Icon,
  tone,
  onDelete,
  deleteLabel = "Delete step",
  onClose,
}: {
  title: string;
  subtitle?: string;
  Icon?: typeof X;
  /** The step kind's gradient (NODE_LOOK.head), so the panel carries its colour. */
  tone?: string;
  onDelete?: () => void;
  deleteLabel?: string;
  onClose: () => void;
}) {
  return (
    <div className="flex items-center gap-2.5 border-b border-zinc-200 px-3.5 py-2.5">
      {Icon && (
        <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", tone ? `bg-gradient-to-br text-white ${tone}` : "bg-indigo-50 text-indigo-600")}><Icon className="h-3.5 w-3.5" /></span>
      )}
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-sm font-semibold text-zinc-900">{title}</h2>
        {subtitle && <p className="truncate text-xs text-zinc-500">{subtitle}</p>}
      </div>
      {onDelete && (
        <button type="button" aria-label={deleteLabel} title={deleteLabel} onClick={onDelete} className="rounded-md p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600 cursor-pointer">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
      <button type="button" aria-label="Close" title="Close" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/** A part of the popup that folds away, with a one-line summary while folded. */
function Fold({ title, summary, defaultOpen = false, children }: { title: string; summary: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-zinc-100">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left cursor-pointer hover:bg-zinc-50">
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-semibold text-zinc-900">{title}</span>
          {!open && <span className="block truncate text-xs text-zinc-500">{summary}</span>}
        </span>
        {open ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
      </button>
      {open && <div className="space-y-3 px-3.5 pb-3.5">{children}</div>}
    </div>
  );
}

// ── Steps ────────────────────────────────────────────────────────────────────

export function StepInspector({
  node,
  nodes,
  edges,
  agents,
  standaloneAgents,
  problems,
  token,
  workflowId,
  lastRunId,
  onChange,
  onEdgeChange,
  onDelete,
  onClose,
}: {
  workflowId: string;
  /** The run the output step's preview reshapes (the one on screen, else the latest). */
  lastRunId?: string | null;
  node: WorkflowNode;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  agents: Record<string, Agent>;
  standaloneAgents: Agent[];
  problems: Problem[];
  token: string;
  onChange: (patch: Partial<WorkflowNode>) => void;
  onEdgeChange: (edgeId: string, patch: Partial<WorkflowEdge>) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const meta = NODE_META[node.type];
  const out = edges.filter((e) => e.source === node.id);
  const title = (id: string) => {
    const n = nodes.find((x) => x.id === id);
    return n ? n.label || (n.type === "agent" ? n.draft_agent?.name || agents[n.agent_id ?? ""]?.name : null) || NODE_META[n.type].title : id;
  };

  const retries = !isTrigger(node.type) && node.type !== "output" && node.type !== "join";
  const attempts = node.retry?.max_attempts ?? 1;
  // An agent step keeps its name and attempts in its Agent overview.
  const inOverview = node.type === "agent" && (!!node.draft_agent || (!!node.agent_id && !!agents[node.agent_id]));
  return (
    <div className="flex max-h-full min-h-0 flex-col">
      <PanelHeader
        title={node.label || meta.title}
        subtitle={node.label ? meta.title : meta.hint}
        Icon={NODE_LOOK[node.type].Icon}
        tone={NODE_LOOK[node.type].head}
        onDelete={isTrigger(node.type) ? undefined : onDelete}
        onClose={onClose}
      />
      <Problems problems={problems} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!inOverview && <Fold title={retries ? "Name and retries" : "Name"} summary={`${node.label || "No label"}${retries ? ` · ${attempts === 1 ? "no retry" : `${attempts} attempts`}` : ""}`}>
          <Field label="Label" hint="Shown on the canvas and in run history.">
            <Input className="h-9" value={node.label ?? ""} placeholder={meta.title} onChange={(e) => onChange({ label: e.target.value || null })} />
          </Field>
          {retries && (
            <Field label="Attempts if it fails">
              <Input
                className="h-9"
                type="number"
                min={1}
                max={5}
                value={node.retry?.max_attempts ?? 1}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  onChange({ retry: n > 1 ? { max_attempts: Math.min(5, n) } : null });
                }}
              />
            </Field>
          )}
        </Fold>}

        {isTrigger(node.type) && (
          <Section title="Starts">
            <Select
              value={node.type}
              onChange={(e) => {
                const type = e.target.value as WorkflowNode["type"];
                onChange({
                  type,
                  schedule: type === "schedule_trigger" ? node.schedule ?? { cron: DEFAULT_CRON, timezone: browserTimezone(), enabled: true } : node.schedule,
                });
              }}
            >
              <option value="input">When someone runs it with a request</option>
              <option value="manual_trigger">When someone presses Run</option>
              <option value="schedule_trigger">On a schedule</option>
            </Select>
          </Section>
        )}
        {node.type === "schedule_trigger" && (
          <WorkflowScheduleFields node={node} token={token} workflowId={workflowId} onChange={onChange} />
        )}
        {node.type === "input" && <InputFields node={node} onChange={onChange} />}
        {node.type === "agent" && (
          <AgentStepConfig node={node} agents={agents} standaloneAgents={standaloneAgents} token={token} onChange={onChange} />
        )}
        {node.type === "tool" && <ToolStep node={node} token={token} onChange={onChange} />}
        {node.type === "condition" && (
          <ConditionStep node={node} out={out} title={title} onChange={onChange} onEdgeChange={onEdgeChange} />
        )}
        {node.type === "join" && (
          <Section title="Wait for">
            <Select
              value={node.join_policy?.mode ?? "all"}
              onChange={(e) => onChange({ join_policy: { mode: e.target.value as "all" | "any" | "count", min_required: node.join_policy?.min_required ?? null } })}
            >
              <option value="all">Every branch</option>
              <option value="any">Any branch that succeeds</option>
              <option value="count">At least N branches</option>
            </Select>
            {node.join_policy?.mode === "count" && (
              <Field label="How many">
                <Input className="h-9" type="number" min={1} value={node.join_policy.min_required ?? 1} onChange={(e) => onChange({ join_policy: { mode: "count", min_required: Number(e.target.value) || 1 } })} />
              </Field>
            )}
          </Section>
        )}
        {node.type === "human_approval" && (
          <Section title="Approval">
            <Field label="Message to the approver" hint="Approving continues the workflow; rejecting stops it.">
              <Textarea rows={3} value={node.approval_message ?? ""} onChange={(e) => onChange({ approval_message: e.target.value })} />
            </Field>
          </Section>
        )}
        {node.type === "output" && (
          <OutputSettings
            config={node.output_config}
            incoming={edges.filter((e) => e.target === node.id).length}
            token={token}
            workflowId={workflowId}
            nodeId={node.id}
            lastRunId={lastRunId}
            onChange={(output_config) => onChange({ output_config })}
          />
        )}
      </div>
    </div>
  );
}

function InputFields({ node, onChange }: { node: WorkflowNode; onChange: (p: Partial<WorkflowNode>) => void }) {
  const vars = node.variables ?? [];
  const setVar = (i: number, patch: Partial<InputVariable>) => onChange({ variables: vars.map((v, j) => (j === i ? { ...v, ...patch } : v)) });
  return (
    <Section
      title="Fields to fill in when it runs"
      action={
        <button type="button" className="text-xs font-medium text-indigo-600 cursor-pointer" onClick={() => onChange({ variables: [...vars, { name: `field_${vars.length + 1}`, type: "text", required: false }] })}>
          <span className="inline-flex items-center gap-0.5"><Plus className="h-3 w-3" /> Add</span>
        </button>
      }
    >
      {vars.length === 0 && <p className="text-xs text-zinc-400">Only the request text. Add fields for structured inputs (a customer name, an amount…).</p>}
      {vars.map((v, i) => (
        <div key={i} className="space-y-2 rounded-lg border border-zinc-200 p-2.5">
          <div className="flex gap-2">
            <Input className="h-8 font-mono text-xs" value={v.name} onChange={(e) => setVar(i, { name: e.target.value.replace(/[^A-Za-z0-9_]/g, "_") })} />
            <button type="button" aria-label="Remove field" onClick={() => onChange({ variables: vars.filter((_, j) => j !== i) })} className="text-zinc-400 hover:text-red-600 cursor-pointer">
              <X className="h-4 w-4" />
            </button>
          </div>
          <Input className="h-8 text-xs" placeholder="Label shown to people" value={v.label ?? ""} onChange={(e) => setVar(i, { label: e.target.value || null })} />
          <div className="flex items-center gap-3">
            <Select className="h-8 text-xs" value={v.type ?? "text"} onChange={(e) => setVar(i, { type: e.target.value as InputVariable["type"] })}>
              <option value="text">Text</option>
              <option value="number">Number</option>
              <option value="boolean">Yes/no</option>
              <option value="json">JSON</option>
            </Select>
            <Toggle label="Required" checked={!!v.required} onChange={(r) => setVar(i, { required: r })} />
          </div>
        </div>
      ))}
    </Section>
  );
}

function ToolStep({ node, token, onChange }: { node: WorkflowNode; token: string; onChange: (p: Partial<WorkflowNode>) => void }) {
  const serverId = serverIdOf(node.tool_id);
  const server = useQuery({
    queryKey: ["builder-server-tools", serverId],
    queryFn: () => builderApi.serverTools(token, serverId!),
    enabled: !!token && !!serverId,
  });
  const tool = server.data?.tools.find((t) => t.name === toolName(node.tool_id));
  return (
    <>
      <Section title="What it does">
        <Field label="In words" hint="Used to find the tool, and kept so it can be found again.">
          <Input className="h-9" value={node.need ?? ""} onChange={(e) => onChange({ need: e.target.value })} />
        </Field>
        {node.tool_id ? (
          <div className="rounded-lg border border-zinc-200 p-2.5">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-zinc-900">{server.data ? `${server.data.server_name}.` : ""}{toolName(node.tool_id)}</span>
              {tool && <RiskBadge risk={tool.risk.risk} />}
              {server.data && !server.data.connected && <span className="ml-auto text-xs text-amber-600">connect first</span>}
            </div>
            {tool?.description && <p className="mt-1 text-xs text-zinc-500">{tool.description}</p>}
            <button type="button" className="mt-1 text-xs text-indigo-600 cursor-pointer" onClick={() => onChange({ tool_id: null, tool_args: null })}>
              Change tool
            </button>
          </div>
        ) : (
          <ToolPicker token={token} initialQuery={node.need ?? ""} onPick={(t) => onChange({ tool_id: t.tool_id, need: node.need || t.description })} />
        )}
      </Section>
      {node.tool_id && (
        <Section title="Arguments">
          <Field label="Fixed values" hint="Always used, e.g. {&quot;channel&quot;: &quot;#sales&quot;}. The rest are filled from the step's text; anything still missing is asked of you at run time.">
            <JsonField value={node.tool_args} onChange={(v) => onChange({ tool_args: v })} />
          </Field>
          <Field label="Send this text instead of the previous step's" hint="Optional.">
            <Textarea rows={2} value={node.message_template ?? ""} onChange={(e) => onChange({ message_template: e.target.value || null })} />
          </Field>
        </Section>
      )}
    </>
  );
}

function ConditionStep({
  node,
  out,
  title,
  onChange,
  onEdgeChange,
}: {
  node: WorkflowNode;
  out: WorkflowEdge[];
  title: (id: string) => string;
  onChange: (p: Partial<WorkflowNode>) => void;
  onEdgeChange: (edgeId: string, patch: Partial<WorkflowEdge>) => void;
}) {
  const cfg = node.condition_config ?? {};
  const mode = cfg.mode ?? "ai";
  const rules = cfg.rules ?? {};
  const setCfg = (patch: Partial<NonNullable<WorkflowNode["condition_config"]>>) => onChange({ condition_config: { ...cfg, ...patch } });
  const setRule = (target: string, rule: ConditionRule | null) => {
    const next = { ...rules };
    if (rule) next[target] = rule;
    else delete next[target];
    setCfg({ rules: next });
  };
  return (
    <Section title="How it decides">
      <Select value={mode} onChange={(e) => setCfg({ mode: e.target.value as "ai" | "rule" })}>
        <option value="ai">AI picks a line by its label</option>
        <option value="rule">Rules (no AI)</option>
      </Select>
      {mode === "ai" && (
        <Field label="Extra guidance" hint="e.g. classify by urgency">
          <Textarea rows={2} value={cfg.instructions ?? ""} onChange={(e) => setCfg({ instructions: e.target.value || null })} />
        </Field>
      )}
      {out.length === 0 && <p className="text-xs text-amber-700">Connect this step to two or more steps to give it lines to choose from.</p>}
      {out.map((e) => {
        const rule = rules[e.target];
        return (
          <div key={e.id} className="space-y-2 rounded-lg border border-zinc-200 p-2.5">
            <p className="text-xs text-zinc-500">Line to <span className="font-medium text-zinc-800">{title(e.target)}</span></p>
            <Input className="h-8 text-xs" placeholder="Label, e.g. Approved" value={e.condition ?? ""} onChange={(ev) => onEdgeChange(e.id, { condition: ev.target.value || null })} />
            {mode === "rule" && (
              <div className="grid grid-cols-3 gap-1.5">
                <Input className="h-8 text-xs" placeholder="text" value={rule?.field ?? "text"} onChange={(ev) => setRule(e.target, { ...(rule ?? { op: "contains" }), field: ev.target.value })} />
                <Select className="h-8 text-xs" value={rule?.op ?? ""} onChange={(ev) => setRule(e.target, ev.target.value ? { ...(rule ?? {}), op: ev.target.value } : null)}>
                  <option value="">no rule</option>
                  {RULE_OPS.map((op) => <option key={op} value={op}>{op.replace("_", " ")}</option>)}
                </Select>
                <Input className="h-8 text-xs" placeholder="value" value={rule?.value ?? ""} onChange={(ev) => rule && setRule(e.target, { ...rule, value: ev.target.value })} />
              </div>
            )}
          </div>
        );
      })}
      {out.length > 0 && (
        <Field label="If nothing matches, go to">
          <Select value={cfg.default_branch ?? ""} onChange={(e) => setCfg({ default_branch: e.target.value || null })}>
            <option value="">The unlabelled line (or the first)</option>
            {out.map((e) => <option key={e.id} value={e.target}>{title(e.target)}</option>)}
          </Select>
        </Field>
      )}
    </Section>
  );
}

// ── A line ───────────────────────────────────────────────────────────────────

export function EdgeInspector({
  edge,
  fromCondition,
  onChange,
  onDelete,
  onClose,
}: {
  edge: WorkflowEdge;
  fromCondition: boolean;
  onChange: (patch: Partial<WorkflowEdge>) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  return (
    <div className="flex max-h-full min-h-0 flex-col">
      <PanelHeader title="Line" subtitle={`${edge.source} → ${edge.target}`} onDelete={onDelete} deleteLabel="Remove line" onClose={onClose} />
      {fromCondition && (
        <Section title="Branch label">
          <Input className="h-9" value={edge.condition ?? ""} onChange={(e) => onChange({ condition: e.target.value || null })} />
          <p className="text-xs text-zinc-400">In AI mode the condition picks a line by this label.</p>
        </Section>
      )}
      {!fromCondition && <p className="px-3.5 py-3 text-xs text-zinc-500">A plain line: the next step gets this one&apos;s output.</p>}
    </div>
  );
}
