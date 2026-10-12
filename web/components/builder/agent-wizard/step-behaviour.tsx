"use client";

import { Hand, MessageSquare, ShieldCheck } from "lucide-react";

import { AgentFields } from "@/components/builder/agent-fields";
import { BareSections } from "@/components/builder/fields";
import { GuardrailFields } from "@/components/builder/guardrail-fields";
import { AiNote, Badge, Category, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { guardrailsOn } from "@/lib/builder/agent-wizard";
import { serverIdOf, toolName } from "@/lib/builder/graph";
import type { Risk } from "@/lib/builder/types";

const RISK_WORDS: Record<Risk, string> = { read: "only read", edit: "change data", delete: "delete" };

/** Step four: safety checks, when it stops to ask, and how it writes. */
export function BehaviourStep({ token, draft, update, toolMeta, servers, guardrailReason }: StepProps & { guardrailReason: string | null }) {
  const config = draft.config;
  const checks = guardrailsOn(config.guardrails);
  const counts: Record<Risk, number> = { read: 0, edit: 0, delete: 0 };
  for (const id of config.tool_ids ?? []) {
    const risk = servers[serverIdOf(id) ?? ""]?.tools.find((t) => t.name === toolName(id))?.risk ?? toolMeta[id]?.risk;
    if (risk) counts[risk] += 1;
  }
  const riskLine = (Object.keys(counts) as Risk[])
    .filter((r) => counts[r])
    .map((r) => `${counts[r]} that ${RISK_WORDS[r]}`)
    .join(", ");

  return (
    <BareSections.Provider value>
      <div className="space-y-3">
        <Category
          icon={ShieldCheck}
          tone="emerald"
          title="Safety checks"
          hint="Run around every request and answer. Each one you turn on is listed on the review."
          badge={<Badge tone={checks.length ? "emerald" : "zinc"}>{checks.length ? `${checks.length} on` : "Off"}</Badge>}
        >
          {guardrailReason && <AiNote>Suggested for this agent: {guardrailReason}</AiNote>}
          <GuardrailFields
            agent={draft}
            value={config.guardrails ?? {}}
            hasKnowledge={(config.knowledge_base_ids ?? []).length > 0}
            token={token}
            onChange={(guardrails) => update({ ...draft, config: { ...config, guardrails } })}
          />
        </Category>

        <Category icon={Hand} tone="rose" title="Ask me first" hint="It pauses and waits for your OK before running these kinds of tools.">
          <p className="rounded-lg bg-zinc-50 p-2.5 text-xs text-zinc-600">
            {riskLine ? `Its tools: ${riskLine}.` : "It has no tools yet, so there's nothing to approve."} Asking first for anything that changes or deletes data is the safe default.
          </p>
          <AgentFields value={draft} onChange={update} token={token} only={["approvals"]} />
        </Category>

        <Category icon={MessageSquare} tone="sky" title="How it replies" hint="Tone, length, language, and whether it cites its sources.">
          <AgentFields value={draft} onChange={update} token={token} only={["answers"]} />
        </Category>
      </div>
    </BareSections.Provider>
  );
}
