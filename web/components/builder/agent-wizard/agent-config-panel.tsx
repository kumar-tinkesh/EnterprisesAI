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
import { cn } from "@/lib/utils";

export type ConfigTab = "identity" | "abilities" | "behaviour" | "engine" | "chat" | "team" | "schedule";

const TABS: { id: ConfigTab; label: string; title: string; hint: string }[] = [
  ...WIZARD_STEPS.filter((s) => s.id !== "describe" && s.id !== "review").map((s) => ({ id: s.id as ConfigTab, label: s.label, title: s.title, hint: s.hint })),
  { id: "chat", label: "Chat & memory", title: "What do people see, and what does it remember?", hint: "A welcome line and suggested questions for an empty chat, and a long-term memory of each person." },
  { id: "team", label: "Team", title: "Who can it hand work to?", hint: "Other agents it may ask to do part of a task, each with its own tools and knowledge." },
  { id: "schedule", label: "Triggers", title: "When should it run by itself?", hint: "On a timetable, or whenever something posts to its webhook URL. Results land in its run history." },
];

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

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [tab]);

  const current = TABS.find((t) => t.id === tab) ?? TABS[0];
  const props: StepProps = {
    token, draft: value, update: onChange, insights: null, toolMeta: meta, addMeta, servers,
    profiles: profiles.data ?? [],
    goTo: (s) => TABS.some((t) => t.id === s) && onTab(s as ConfigTab),
    connect: setConnecting,
  };

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-900">Agent settings</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <nav aria-label="Settings" className="border-b border-zinc-200">
        <ul className="flex gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none]">
          {TABS.map((t) => (
            <li key={t.id} className="shrink-0">
              <button
                type="button"
                aria-current={t.id === tab ? "page" : undefined}
                onClick={() => onTab(t.id)}
                className={cn(
                  "rounded-lg px-2.5 py-1.5 text-xs font-medium cursor-pointer",
                  t.id === tab ? "bg-indigo-50 text-indigo-700" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900",
                )}
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div ref={body} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="space-y-4 p-3 sm:p-4">
          <div>
            <h3 className="text-base font-semibold text-zinc-900">{current.title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-zinc-500">{current.hint}</p>
            {readOnly && <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">View only — shared by a teammate.</p>}
          </div>
          <fieldset disabled={readOnly} className="min-w-0 space-y-3">
            {tab === "identity" && <IdentityStep {...props} />}
            {tab === "abilities" && <AbilitiesStep {...props} />}
            {tab === "behaviour" && <BehaviourStep {...props} guardrailReason={null} />}
            {tab === "engine" && <EngineStep {...props} />}
            {tab === "chat" && <ChatStep {...props} />}
            {tab === "team" && <TeamStep {...props} agentId={agentId} />}
          </fieldset>
          {/* Yours, even on a teammate's agent: outside the owner-only fieldset. */}
          {tab === "chat" && (
            <Category icon={UserRound} tone="violet" title="Your memories" hint="Only you see these. It uses them when its memory is on.">
              <MyMemories agentId={agentId} token={token} />
            </Category>
          )}
          {tab === "schedule" && (
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
        </div>
      </div>
      {connecting && <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />}
    </div>
  );
}
