"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, ChevronDown, FileUp, Lightbulb, Link2, Plus, Search, Server, Trash2, Wrench, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { RiskBadge } from "@/components/builder/fields";
import { ToolPicker } from "@/components/builder/tool-picker";
import { ConnectButton, useConnectedServers } from "@/components/connections/connect-button";
import { AiNote, Badge, Category, type ServerInfo, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { ApiError, knowledgeApi } from "@/lib/api";
import { accessOf, groupByServer, presetToolIds, replaceServerTools, type Access } from "@/lib/builder/agent-wizard";
import { toolName } from "@/lib/builder/graph";
import type { ToolCandidate } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** Step three: the tools it may call (grouped by server, with how much it may do on each) and its documents. */
export function AbilitiesStep(props: StepProps) {
  const { token, draft, update, insights, toolMeta, addMeta, servers } = props;
  const toolIds = draft.config.tool_ids ?? [];
  const groups = groupByServer(toolIds);
  const related = (insights?.related_tools ?? []).filter((t) => !toolIds.includes(t.tool_id));
  const isConnected = useConnectedServers(token);
  const setTools = (ids: string[]) => update({ ...draft, config: { ...draft.config, tool_ids: ids } });
  const addTool = (t: ToolCandidate) => {
    addMeta([t]);
    if (!toolIds.includes(t.tool_id)) setTools([...toolIds, t.tool_id]);
  };

  return (
    <div className="space-y-3">
      <Category
        icon={Wrench}
        tone="emerald"
        title="Tools it will use"
        hint="Grouped by the app they belong to. Choose how much it may do in each one."
        badge={<Badge tone="emerald">{toolIds.length}</Badge>}
      >
        {groups.length === 0 ? (
          <p className="rounded-lg bg-zinc-50 p-3 text-xs text-zinc-500">
            {insights?.needs
              ? `None of your connected apps matched "${insights.needs}". Search below, or ask your admin to add an app that can.`
              : "No tools — it works only from what it's asked and its documents. Add some below if it should act in your apps."}
          </p>
        ) : (
          groups.map((g) => (
            <ServerCard
              key={g.serverId}
              info={servers[g.serverId]}
              selected={g.toolIds}
              meta={toolMeta}
              onChange={(ids) => setTools(replaceServerTools(toolIds, g.serverId, ids))}
              onConnect={() => props.connect(g.serverId)}
            />
          ))
        )}
      </Category>

      {related.length > 0 && (
        <Category icon={Lightbulb} tone="amber" title="You might also want" hint="Other tools that matched your description but weren't picked." badge={<Badge tone="amber">{related.length}</Badge>}>
          <ul className="space-y-1.5">
            {related.map((t) => (
              <li key={t.tool_id} className="flex items-start gap-2 rounded-lg border border-zinc-200 p-2.5">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-zinc-900">
                    <span className="break-all">{t.tool_name}</span>
                    <RiskBadge risk={t.risk} />
                    <span className="font-normal text-zinc-400">{t.server_name}</span>
                    {isConnected(t.server_id, t.connected) && <CheckCircle2 className="h-3 w-3 text-emerald-600" aria-label="Connected" />}
                  </p>
                  {t.description && <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">{t.description}</p>}
                </div>
                {!isConnected(t.server_id, t.connected) && <ConnectButton serverId={t.server_id} token={token} className="py-1.5" />}
                <button
                  type="button"
                  onClick={() => addTool(t)}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-2 py-1.5 text-xs font-medium text-indigo-600 hover:bg-zinc-50 cursor-pointer"
                >
                  <Plus className="h-3 w-3" /> Add
                </button>
              </li>
            ))}
          </ul>
        </Category>
      )}

      <Category icon={Search} tone="sky" title="Find another tool" hint="Describe what it should be able to do; we search every app you can use." defaultOpen={toolIds.length === 0}>
        <ToolPicker token={token} exclude={toolIds} onPick={addTool} />
      </Category>

      <KnowledgeCategory {...props} />
    </div>
  );
}

const ACCESS: { id: Exclude<Access, "none">; label: string; hint: string }[] = [
  { id: "read", label: "Read only", hint: "Look things up, never change anything" },
  { id: "readwrite", label: "Read & write", hint: "Look up and create or update (never delete)" },
  { id: "custom", label: "Custom", hint: "Exactly the tools ticked below" },
];

function ServerCard({
  info,
  selected,
  meta,
  onChange,
  onConnect,
}: {
  info: ServerInfo | undefined;
  selected: string[];
  meta: Record<string, ToolCandidate>;
  onChange: (ids: string[]) => void;
  onConnect: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  if (!info) return null;
  const access = accessOf(info.serverId, selected, info.tools);
  const has = new Set(selected);
  const toggle = (name: string, on: boolean) => {
    const id = `mcp:${info.serverId}:${name}`;
    onChange(on ? [...selected, id] : selected.filter((x) => x !== id));
  };

  return (
    <div className={cn("rounded-xl border p-3", info.connected ? "border-zinc-200" : "border-amber-300")}>
      <div className="flex flex-wrap items-center gap-2">
        <Server className="h-4 w-4 shrink-0 text-zinc-400" />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-900">{info.name}</p>
        {info.loading ? (
          <Spinner className="h-3.5 w-3.5 text-zinc-400" />
        ) : info.connected ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
            <CheckCircle2 className="h-3.5 w-3.5" /> Connected
          </span>
        ) : (
          <button
            type="button"
            onClick={onConnect}
            className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800 hover:bg-amber-100 cursor-pointer"
          >
            <Link2 className="h-3 w-3" /> Connect
          </button>
        )}
        <button
          type="button"
          aria-label={`Remove ${info.name}`}
          title="Remove all its tools"
          onClick={() => onChange([])}
          className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-red-600 cursor-pointer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {!info.connected && !info.loading && (
        <p className="mt-1.5 text-xs text-amber-700">Not connected yet. You can still create the agent; these tools run once you connect.</p>
      )}
      {info.missing && <p className="mt-1.5 text-xs text-red-600">This app is no longer available to you.</p>}

      {info.tools.length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-zinc-100 p-1" role="radiogroup" aria-label={`What it may do in ${info.name}`}>
          {ACCESS.map((a) => {
            const on = access === a.id;
            return (
              <button
                key={a.id}
                type="button"
                role="radio"
                aria-checked={on}
                title={a.hint}
                onClick={() => (a.id === "custom" ? setShowAll(true) : onChange(presetToolIds(info.serverId, info.tools, a.id)))}
                className={cn(
                  "rounded-md px-1.5 py-1.5 text-xs font-medium leading-tight cursor-pointer",
                  on ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-900",
                )}
              >
                {a.label}
              </button>
            );
          })}
        </div>
      )}

      <ul className="mt-2 space-y-1">
        {selected.map((id) => {
          const name = toolName(id);
          const tool = info.tools.find((t) => t.name === name);
          const why = meta[id]?.reason;
          return (
            <li key={id} className="flex items-start gap-2 rounded-lg bg-zinc-50 px-2.5 py-2">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-zinc-900">
                  <span className="break-all">{name}</span>
                  {(tool?.risk ?? meta[id]?.risk) && <RiskBadge risk={(tool?.risk ?? meta[id]?.risk)!} />}
                </p>
                {why && <p className="mt-0.5 text-xs text-indigo-700">Why: {why}</p>}
              </div>
              <button type="button" aria-label={`Remove ${name}`} onClick={() => onChange(selected.filter((x) => x !== id))} className="rounded p-0.5 text-zinc-400 hover:text-red-600 cursor-pointer">
                <X className="h-3.5 w-3.5" />
              </button>
            </li>
          );
        })}
      </ul>

      {info.tools.length > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((s) => !s)}
          aria-expanded={showAll}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer"
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showAll && "rotate-180")} />
          {showAll ? "Hide" : "Choose from"} all {info.tools.length} tools in {info.name} ({selected.length} on)
        </button>
      )}
      {showAll && (
        <ul className="mt-2 max-h-72 space-y-0.5 overflow-y-auto rounded-lg border border-zinc-100 p-1">
          {info.tools.map((t) => {
            const id = `mcp:${info.serverId}:${t.name}`;
            return (
              <li key={t.name}>
                <label className="flex cursor-pointer items-start gap-2 rounded-md p-2 hover:bg-zinc-50">
                  <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-indigo-600" checked={has.has(id)} onChange={(e) => toggle(t.name, e.target.checked)} />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-zinc-900">
                      <span className="break-all">{t.name}</span>
                      <RiskBadge risk={t.risk} />
                    </span>
                    {t.description && <span className="mt-0.5 block line-clamp-2 text-xs text-zinc-500">{t.description}</span>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Documents: pick knowledge bases, make a new one, and put files in it — all without leaving the setup. */
function KnowledgeCategory({ token, draft, update, insights }: StepProps) {
  const queryClient = useQueryClient();
  const kbIds = draft.config.knowledge_base_ids ?? [];
  const setKbs = (ids: string[]) => update({ ...draft, config: { ...draft.config, knowledge_base_ids: ids } });
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });
  const [name, setName] = useState("");
  const [uploading, setUploading] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const fileFor = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const recommended = !!insights?.knowledge.recommended;

  const create = useMutation({
    mutationFn: () => knowledgeApi.create(token, { name: name.trim() }),
    onSuccess: (kb) => {
      setName("");
      setKbs([...kbIds, kb.id]);
      setMessage({ tone: "ok", text: `Created "${kb.name}". Add a file so it has something to search.` });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases", token] });
    },
    onError: (err) => setMessage({ tone: "error", text: err instanceof ApiError ? err.message : "Couldn't create the knowledge base." }),
  });

  const upload = async (files: FileList | null) => {
    const kbId = fileFor.current;
    if (!kbId || !files?.length) return;
    setUploading(kbId);
    setMessage(null);
    try {
      for (const file of Array.from(files)) await knowledgeApi.uploadDocument(token, kbId, file);
      setMessage({ tone: "ok", text: `Added ${files.length} file${files.length === 1 ? "" : "s"}. They're searchable once processing finishes.` });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases", token] });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : "Upload failed." });
    } finally {
      setUploading(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const list = kbs.data ?? [];
  return (
    <Category
      icon={BookOpen}
      tone="violet"
      title="Documents it can search"
      hint="Knowledge bases it reads before answering — policies, manuals, price lists."
      badge={recommended ? <Badge tone="indigo">Suggested</Badge> : kbIds.length ? <Badge tone="violet">{kbIds.length}</Badge> : undefined}
      defaultOpen={recommended || kbIds.length > 0}
    >
      {recommended && <AiNote>{insights?.knowledge.reason || "Your description says it should answer from your own documents."} Attach a knowledge base with them.</AiNote>}
      <input ref={fileInput} type="file" multiple className="hidden" onChange={(e) => void upload(e.target.files)} />

      {kbs.isLoading ? (
        <Spinner className="h-4 w-4 text-zinc-400" />
      ) : list.length === 0 ? (
        <p className="text-xs text-zinc-500">You don&apos;t have a knowledge base yet. Create one below.</p>
      ) : (
        <ul className="space-y-1.5">
          {list.map((kb) => {
            const on = kbIds.includes(kb.id);
            return (
              <li key={kb.id} className={cn("flex flex-wrap items-center gap-2 rounded-lg border p-2.5", on ? "border-indigo-400" : "border-zinc-200")}>
                <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4 shrink-0 accent-indigo-600"
                    checked={on}
                    onChange={(e) => setKbs(e.target.checked ? [...kbIds, kb.id] : kbIds.filter((k) => k !== kb.id))}
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium text-zinc-900">{kb.name}</span>
                    <span className={cn("block text-xs", kb.document_count ? "text-zinc-500" : "text-amber-700")}>
                      {kb.document_count ? `${kb.document_count} document${kb.document_count === 1 ? "" : "s"}` : "Empty — add a file"}
                    </span>
                  </span>
                </label>
                {on && (
                  <button
                    type="button"
                    disabled={uploading !== null}
                    onClick={() => {
                      fileFor.current = kb.id;
                      fileInput.current?.click();
                    }}
                    className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 cursor-pointer"
                  >
                    {uploading === kb.id ? <Spinner className="h-3 w-3" /> : <FileUp className="h-3 w-3" />} Add files
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && !create.isPending) create.mutate();
        }}
      >
        <Input className="h-9 min-w-0 flex-1 text-xs" placeholder="New knowledge base, e.g. Refund policy" maxLength={255} value={name} onChange={(e) => setName(e.target.value)} aria-label="New knowledge base name" />
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-3 text-xs font-medium text-indigo-600 hover:bg-zinc-50 disabled:opacity-40 cursor-pointer"
        >
          {create.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />} Create
        </button>
      </form>
      {message && <p className={cn("text-xs", message.tone === "ok" ? "text-emerald-700" : "text-red-600")} role="status">{message.text}</p>}
    </Category>
  );
}
