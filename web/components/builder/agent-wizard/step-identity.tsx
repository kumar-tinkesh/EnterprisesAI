"use client";

import { ArrowRight, IdCard, Info } from "lucide-react";

import { AgentFields } from "@/components/builder/agent-fields";
import { BareSections } from "@/components/builder/fields";
import { AiNote, Category, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";

/** Step two: name, role, goal and instructions — what the model is told on every run. */
export function IdentityStep({ token, draft, update, insights, goTo }: StepProps) {
  return (
    <div className="space-y-3">
      <Category icon={IdCard} title="Name and job" hint="The goal is what it does on every run; the instructions are its expertise and its limits.">
        {insights && <AiNote>Drafted from your description. Change anything, or use Improve to polish the goal or instructions.</AiNote>}
        <BareSections.Provider value>
          <AgentFields value={draft} onChange={update} token={token} only={["identity"]} />
        </BareSections.Provider>
      </Category>

      {insights?.needs && (
        <Category icon={Info} tone="sky" title="What it will work with" hint="What the AI understood it needs from outside. Its tools are chosen from this.">
          <p className="rounded-lg bg-zinc-50 p-2.5 text-xs leading-relaxed text-zinc-700">{insights.needs}</p>
          <button type="button" onClick={() => goTo("abilities")} className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer">
            See the tools it picked <ArrowRight className="h-3 w-3" />
          </button>
        </Category>
      )}
    </div>
  );
}
