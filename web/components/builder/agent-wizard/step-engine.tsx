"use client";

import { Gauge, PiggyBank, Scale, SlidersHorizontal, Sparkles, Zap, type LucideIcon } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { AgentFields } from "@/components/builder/agent-fields";
import { BareSections } from "@/components/builder/fields";
import { AiNote, Badge, Category, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { applyProfile, matchingProfile } from "@/lib/builder/agent-wizard";
import type { ProfileId } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

const ICONS: Record<ProfileId, LucideIcon> = { quality: Sparkles, balanced: Scale, speed: Zap, cost: PiggyBank };

/** Step five: one click picks a profile; everything it sets stays editable underneath. */
export function EngineStep({ token, draft, update, insights, profiles }: StepProps) {
  const config = draft.config;
  const current = matchingProfile(config, profiles);
  const aiPick = insights?.profile;

  return (
    <div className="space-y-3">
      <Category icon={Gauge} title="Profile" hint="Sets the model's effort, answer length, retries and how many tools it may call.">
        {aiPick && insights?.profile_reason && (
          <AiNote>
            Picked <strong>{profiles.find((p) => p.id === aiPick)?.label ?? aiPick}</strong>: {insights.profile_reason}
          </AiNote>
        )}
        {profiles.length === 0 ? (
          <Spinner className="h-4 w-4 text-zinc-400" />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Profile">
            {profiles.map((p) => {
              const Icon = ICONS[p.id] ?? Gauge;
              const on = current?.id === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => update({ ...draft, config: applyProfile(config, p) })}
                  className={cn(
                    "flex items-start gap-3 rounded-xl border p-3 text-left transition-colors cursor-pointer",
                    on ? "border-indigo-400 bg-indigo-50" : "border-zinc-200 hover:bg-zinc-50",
                  )}
                >
                  <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", on ? "text-indigo-600" : "text-zinc-400")} />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-zinc-900">
                      {p.label}
                      {aiPick === p.id && <Badge tone="indigo">AI pick</Badge>}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-snug text-zinc-500">{p.summary}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
        {profiles.length > 0 && !current && (
          <p className="text-[11px] text-amber-700">Custom — you changed the settings below. Pick a profile to reset them.</p>
        )}
      </Category>

      <Category icon={SlidersHorizontal} tone="zinc" title="Advanced settings" hint="Model, thinking, answer length, retries, fallback and tool limits." defaultOpen={false}>
        <BareSections.Provider value>
          <AgentFields value={draft} onChange={update} token={token} only={["model", "limits"]} />
        </BareSections.Provider>
      </Category>
    </div>
  );
}
