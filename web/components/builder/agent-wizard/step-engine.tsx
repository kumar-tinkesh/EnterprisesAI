"use client";

import { Gauge, PiggyBank, Scale, SlidersHorizontal, Sparkles, Zap, type LucideIcon } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { AgentFields } from "@/components/builder/agent-fields";
import { BareSections, Field, Select } from "@/components/builder/fields";
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
  const setConfig = (patch: Partial<typeof config>) => update({ ...draft, config: { ...config, ...patch } });

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

      <Category icon={SlidersHorizontal} tone="zinc" title="Advanced settings" hint="Model, creativity, answer length, retries and tool limits." defaultOpen={false}>
        <BareSections.Provider value>
          <AgentFields value={draft} onChange={update} token={token} only={["model"]} />
        </BareSections.Provider>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Thinking effort" hint="Higher = more careful, slower.">
            <Select
              value={config.llm?.reasoning_effort ?? "auto"}
              onChange={(e) => setConfig({ llm: { ...(config.llm ?? {}), reasoning_effort: e.target.value } })}
            >
              <option value="auto">Auto</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </Select>
          </Field>
          <Field label="Most tool calls per run" hint="1–20. It stops and answers after this many.">
            <Input
              className="h-9"
              type="number"
              inputMode="numeric"
              min={1}
              max={20}
              value={config.tools?.max_calls ?? 8}
              onChange={(e) => setConfig({ tools: { ...(config.tools ?? {}), max_calls: Math.min(20, Math.max(1, Number(e.target.value) || 1)) } })}
            />
          </Field>
        </div>
      </Category>
    </div>
  );
}
