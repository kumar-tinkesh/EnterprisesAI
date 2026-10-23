"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, UserRound, Webhook, X } from "lucide-react";

import { BareSections } from "@/components/builder/fields";
import { AgentSchedules } from "@/components/builder/schedule-fields";
import { ConnectServerDialog } from "@/components/connections/server-connect";
import { AbilitiesStep } from "@/components/builder/agent-wizard/step-abilities";
import { BehaviourStep } from "@/components/builder/agent-wizard/step-behaviour";
import { ChatStep, MyMemories } from "@/components/builder/agent-wizard/step-chat";
import { TeamStep } from "@/components/builder/agent-wizard/step-team";
import { AgentWebhooks } from "@/components/builder/webhook-fields";
import { EngineStep } from "@/components/builder/agent-wizard/step-engine";
import { IdentityStep } from "@/components/builder/agent-wizard/step-identity";
import { Category, useServers, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { WIZARD_STEPS, groupByServer } from "@/lib/builder/agent-wizard";
import { builderApi } from "@/lib/builder/api";
import type { DraftAgent, ToolCandidate } from "@/lib/builder/types";
import { Tabs } from "@/components/ui/tabs";

export type ConfigTab = "identity" | "abilities" | "behaviour" | "engine" | "chat" | "team" | "schedule";

const TABS: { id: ConfigTab; label: string; title: string; hint: string }[] = [
  ...WIZARD_STEPS.filter((s) => s.id !== "describe" && s.id !== "review").map((s) => ({ id: s.id as ConfigTab, label: s.label, title: s.title, hint: s.hint })),
  { id: "chat", label: "Chat & memory", title: "What do people see, and what does it remember?", hint: "A welcome line and suggested questions for an empty chat, and a long-term memory of each person." },
  { id: "team", label: "Team", title: "Who can it hand work to?", hint: "Other agents it may ask to do part of a task, each with its own tools and knowledge." },
  { id: "schedule", label: "Triggers", title: "When should it run by itself?", hint: "On a timetable, or whenever something posts to its webhook URL. Results land in its run history." },
];

/** The panel's four tabs, each a few of the categories above, shown one under the other. */
const GROUPS: { id: string; label: string; tabs: ConfigTab[] }[] = [
  { id: "basics", label: "Basics", tabs: ["identity"] },
  { id: "tools", label: "Tools", tabs: ["abilities", "team"] },
  { id: "behaviour", label: "Behaviour", tabs: ["behaviour", "chat"] },
  { id: "advanced", label: "Advanced", tabs: ["engine", "schedule"] },
];
const groupOf = (tab: ConfigTab) => GROUPS.find((g) => g.tabs.includes(tab)) ?? GROUPS[0];

/**
 * A saved agent's settings, in the same categories the guided setup used to
 * create it — opened from the editor's canvas (the agent, a tool or a
 * document). Changes go to the editor's form; the editor's Save stores them.
 */
export function AgentConfigPanel({
  agentId,
  value,
  onChange,
  token,
  readOnly,
  tab,
  onTab,
  onClose,
}: {
  agentId: string;
  value: DraftAgent;
  onChange: (next: DraftAgent) => void;
  token: string;
  readOnly: boolean;
  tab: ConfigTab;
  onTab: (tab: ConfigTab) => void;
  onClose: () => void;
}) {
  const [meta, setMeta] = useState<Record<string, ToolCandidate>>({});
  const [connecting, setConnecting] = useState<string | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const profiles = useQuery({ queryKey: ["builder-agent-profiles"], queryFn: () => builderApi.agentProfiles(token), enabled: !!token, staleTime: Infinity });
  const serverIds = useMemo(() => groupByServer(value.config.tool_ids ?? []).map((g) => g.serverId), [value.config.tool_ids]);
  const servers = useServers(token, serverIds, meta);
  const addMeta = useCallback((tools: ToolCandidate[]) => setMeta((m) => ({ ...m, ...Object.fromEntries(tools.map((t) => [t.tool_id, t])) })), []);

  // A new tab starts at the top; a category inside the open tab (a tool clicked on the canvas → Team) is scrolled to.
  const group = groupOf(tab);
  useEffect(() => {
    const el = body.current;
    if (!el) return;
    const first = group.tabs[0] === tab;
    const target = first ? null : el.querySelector<HTMLElement>(`[data-section="${tab}"]`);
    el.scrollTo({ top: target ? target.offsetTop - 8 : 0 });
  }, [tab, group]);

  const props: StepProps = {
    token, draft: value, update: onChange, insights: null, toolMeta: meta, addMeta, servers,
    profiles: profiles.data ?? [],
    goTo: (s) => TABS.some((t) => t.id === s) && onTab(s as ConfigTab),
    connect: setConnecting,
  };

  // One category's fields (a plain function, not a component, so typing keeps its focus).
  const renderSection = (t: ConfigTab) => (
    <>
      <fieldset disabled={readOnly} className="min-w-0 space-y-3">
        {t === "identity" && <IdentityStep {...props} />}
        {t === "abilities" && <AbilitiesStep {...props} />}
        {t === "behaviour" && <BehaviourStep {...props} guardrailReason={null} />}
        {t === "engine" && <EngineStep {...props} />}
        {t === "chat" && <ChatStep {...props} />}
        {t === "team" && <TeamStep {...props} agentId={agentId} />}
      </fieldset>
      {/* Yours, even on a teammate's agent: outside the owner-only fieldset. */}
      {t === "chat" && (
        <Category icon={UserRound} tone="violet" title="Your memories" hint="Only you see these. It uses them when its memory is on.">
          <MyMemories agentId={agentId} token={token} />
        </Category>
      )}
      {t === "schedule" && (
        <>
          <Category icon={CalendarClock} tone="sky" title="Schedules" hint="Each one runs the saved version of this agent.">
            <BareSections.Provider value>
              <AgentSchedules agentId={agentId} token={token} />
            </BareSections.Provider>
          </Category>
          <Category icon={Webhook} tone="emerald" title="Webhooks" hint="A URL that runs it on whatever is posted: a form, Zapier, a Slack command, forwarded email.">
            <BareSections.Provider value>
              <AgentWebhooks agentId={agentId} token={token} />
            </BareSections.Provider>
          </Category>
        </>
      )}
    </>
  );

  return (
    <div className="flex h-full flex-col bg-[var(--surface)]">
      <div className="flex items-center justify-between px-4 pt-3">
        <h2 className="text-base font-semibold text-zinc-900">Agent settings</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="px-2 pt-1">
        <Tabs value={group.id} onChange={(g) => onTab(GROUPS.find((x) => x.id === g)!.tabs[0])} tabs={GROUPS.map((g) => [g.id, g.label] as const)} />
      </div>
      <div ref={body} className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="space-y-6 p-3 sm:p-4">
          {/* The tab names the topic; each card below says what it's for. */}
          {readOnly && <p className="rounded-lg bg-amber-50 p-2.5 text-sm text-amber-800">View only — shared by a teammate.</p>}
          {group.tabs.map((t) => {
            const meta = TABS.find((x) => x.id === t)!;
            return (
              <section key={t} data-section={t} className="space-y-3">
                {/* Two categories share a tab: each says what it is. */}
                {group.tabs.length > 1 && (
                  <div>
                    <h3 className="text-sm font-semibold text-zinc-900">{meta.label}</h3>
                    <p className="text-xs text-zinc-500">{meta.hint}</p>
                  </div>
                )}
                {renderSection(t)}
              </section>
            );
          })}
        </div>
      </div>
      {connecting && <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />}
    </div>
  );
}
