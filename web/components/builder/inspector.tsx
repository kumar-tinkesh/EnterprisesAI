"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Plus, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AgentFields } from "@/components/builder/agent-fields";
import { Field, JsonField, RiskBadge, Section, Select, Textarea, Toggle } from "@/components/builder/fields";
import { ToolPicker } from "@/components/builder/tool-picker";
import { builderApi } from "@/lib/builder/api";
import { NODE_META, isTrigger, serverIdOf, toolName } from "@/lib/builder/graph";
import type {
  Agent,
  ConditionRule,
  InputVariable,
  Problem,
  WorkflowConfig,
  WorkflowEdge,
  WorkflowNode,
} from "@/lib/builder/types";

const RULE_OPS = ["contains", "not_contains", "equals", "not_equals", "starts_with", "ends_with", "gt", "gte", "lt", "lte", "is_empty", "is_not_empty"];

function Problems({ problems }: { problems: Problem[] }) {
  if (!problems.length) return null;
  return (
    <div className="space-y-1 border-b border-red-100 bg-red-50 px-4 py-3">
      {problems.map((p, i) => (
        <p key={i} className="flex gap-1.5 text-xs text-red-700">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {p.message}
        </p>
      ))}
    </div>
  );
}

function PanelHeader({ title, subtitle, onClose }: { title: string; subtitle?: string; onClose: () => void }) {
  return (
    <div className="flex items-start justify-between border-b border-zinc-200 px-4 py-3">
      <div>
        <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
        {subtitle && <p className="text-xs text-zinc-500">{subtitle}</p>}
      </div>
      <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
        <X className="h-4 w-4" />
      </button>
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
  onChange,
  onEdgeChange,
  onDelete,
  onClose,
}: {
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

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title={meta.title} subtitle={meta.hint} onClose={onClose} />
      <Problems problems={problems} />
      <div className="flex-1 overflow-y-auto">
        <Section title="Step">
          <Field label="Label" hint="Shown on the canvas and in run history.">
            <Input className="h-9" value={node.label ?? ""} placeholder={meta.title} onChange={(e) => onChange({ label: e.target.value || null })} />
          </Field>
          {!isTrigger(node.type) && node.type !== "output" && node.type !== "join" && (
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
        </Section>

        {node.type === "input" && <InputFields node={node} onChange={onChange} />}
        {node.type === "agent" && (
          <AgentStep node={node} agents={agents} standaloneAgents={standaloneAgents} token={token} onChange={onChange} />
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
          <Section title="Answer">
            <Field label="Format">
              <Select value={node.output_config?.format ?? "markdown"} onChange={(e) => onChange({ output_config: { ...node.output_config, format: e.target.value } })}>
                <option value="markdown">As written (markdown)</option>
                <option value="formatted">Report (summary, key points…)</option>
                <option value="text">Plain text (SMS / WhatsApp)</option>
                <option value="json">JSON (for apps)</option>
              </Select>
            </Field>
            <Field label="Language" hint="Empty = same language as the answer.">
              <Input className="h-9" value={node.output_config?.language ?? ""} onChange={(e) => onChange({ output_config: { ...node.output_config, language: e.target.value || null } })} />
            </Field>
            <Field label="Header">
              <Input className="h-9" value={node.output_config?.header ?? ""} onChange={(e) => onChange({ output_config: { ...node.output_config, header: e.target.value } })} />
            </Field>
            <Field label="Footer">
              <Input className="h-9" value={node.output_config?.footer ?? ""} onChange={(e) => onChange({ output_config: { ...node.output_config, footer: e.target.value } })} />
            </Field>
          </Section>
        )}
      </div>
      {!isTrigger(node.type) && (
        <div className="border-t border-zinc-200 p-3">
          <Button variant="outline" size="sm" className="w-full text-red-600" onClick={onDelete}>
            <Trash2 /> Delete step
          </Button>
        </div>
      )}
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

function AgentStep({
  node,
  agents,
  standaloneAgents,
  token,
  onChange,
}: {
  node: WorkflowNode;
  agents: Record<string, Agent>;
  standaloneAgents: Agent[];
  token: string;
  onChange: (p: Partial<WorkflowNode>) => void;
}) {
  const saved = node.agent_id ? agents[node.agent_id] : undefined;
  if (node.draft_agent) {
    return (
      <>
        <div className="mx-4 mt-3 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
          {node.agent_id ? "Changes here apply to this workflow only; the original agent stays as it is." : "A new agent for this workflow — it's created when you save."}
        </div>
        <AgentFields value={node.draft_agent} token={token} onChange={(draft) => onChange({ draft_agent: draft })} />
      </>
    );
  }
  return (
    <Section title="Agent">
      <Field label="Use an agent">
        <Select value={node.agent_id ?? ""} onChange={(e) => onChange({ agent_id: e.target.value || null })}>
          <option value="">Choose…</option>
          {saved && !standaloneAgents.some((a) => a.id === saved.id) && <option value={saved.id}>{saved.name} (this workflow)</option>}
          {standaloneAgents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </Select>
      </Field>
      {saved && <p className="text-xs text-zinc-500">{saved.goal}</p>}
      <div className="flex gap-2">
        {saved && (
          <Button variant="outline" size="sm" onClick={() => onChange({ draft_agent: { name: saved.name, role: saved.role, goal: saved.goal, instructions: saved.instructions, llm_provider: saved.llm_provider, llm_model: saved.llm_model, config: saved.config } })}>
            Customize here
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => onChange({ agent_id: null, draft_agent: { name: "New agent", role: "Assistant", goal: "Describe what this step does", instructions: "", config: {} } })}>
          New agent
        </Button>
      </div>
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
              {server.data && !server.data.connected && <span className="ml-auto text-[10px] text-amber-600">connect first</span>}
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
    <div className="flex h-full flex-col">
      <PanelHeader title="Line" subtitle={`${edge.source} → ${edge.target}`} onClose={onClose} />
      {fromCondition && (
        <Section title="Branch label">
          <Input className="h-9" value={edge.condition ?? ""} onChange={(e) => onChange({ condition: e.target.value || null })} />
          <p className="text-xs text-zinc-400">In AI mode the condition picks a line by this label.</p>
        </Section>
      )}
      <div className="p-3">
        <Button variant="outline" size="sm" className="w-full text-red-600" onClick={onDelete}>
          <Trash2 /> Remove line
        </Button>
      </div>
    </div>
  );
}

// ── Workflow settings ────────────────────────────────────────────────────────

export function SettingsPanel({ config, onChange, onClose }: { config: WorkflowConfig; onChange: (c: WorkflowConfig) => void; onClose: () => void }) {
  const approvals = { read: false, edit: true, delete: true, ...(config.approvals ?? {}) };
  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Workflow settings" onClose={onClose} />
      <div className="flex-1 overflow-y-auto">
        <Section title="When a step fails">
          <Select value={config.on_node_failure ?? "abort"} onChange={(e) => onChange({ ...config, on_node_failure: e.target.value as WorkflowConfig["on_node_failure"] })}>
            <option value="abort">Stop the run</option>
            <option value="retry">Try again, then stop</option>
            <option value="skip">Skip it and carry on</option>
          </Select>
          {config.on_node_failure === "retry" && (
            <Field label="Extra attempts">
              <Input className="h-9" type="number" min={0} max={5} value={config.node_retry_count ?? 0} onChange={(e) => onChange({ ...config, node_retry_count: Number(e.target.value) || 0 })} />
            </Field>
          )}
        </Section>
        <Section title="Limits">
          <Field label="Longest run (seconds of work)" hint="Time spent waiting for approvals doesn't count.">
            <Input className="h-9" type="number" min={30} value={config.max_run_seconds ?? 1800} onChange={(e) => onChange({ ...config, max_run_seconds: Number(e.target.value) || 1800 })} />
          </Field>
          <Field label="Most steps per run" hint="Stops a loop that never exits.">
            <Input className="h-9" type="number" min={1} max={500} value={config.max_steps ?? 50} onChange={(e) => onChange({ ...config, max_steps: Number(e.target.value) || 50 })} />
          </Field>
        </Section>
        <Section title="Ask me before tool steps run">
          <Toggle label="Tools that only read" checked={approvals.read} onChange={(v) => onChange({ ...config, approvals: { ...approvals, read: v } })} />
          <Toggle label="Tools that change data" checked={approvals.edit} onChange={(v) => onChange({ ...config, approvals: { ...approvals, edit: v } })} />
          <Toggle label="Tools that delete" checked={approvals.delete} onChange={(v) => onChange({ ...config, approvals: { ...approvals, delete: v } })} />
          <p className="text-xs text-zinc-400">Agent steps also follow their own agent&apos;s rules — the stricter of the two applies.</p>
        </Section>
      </div>
    </div>
  );
}
