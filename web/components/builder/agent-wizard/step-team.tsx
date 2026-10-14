"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, Check, Users } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import { Badge, Category, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { builderApi } from "@/lib/builder/api";
import { cn } from "@/lib/utils";

const MAX_TEAM = 5;

/**
 * The agents this one may hand a task to. Each becomes a tool ("ask_<name>")
 * it calls when that agent's goal fits part of the work; the helper runs with
 * its own tools and knowledge, as the same person, and its answer comes back.
 */
export function TeamStep({ token, draft, update, agentId }: StepProps & { agentId?: string }) {
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const config = draft.config;
  const team = config.sub_agent_ids ?? [];
  const others = (agents.data ?? []).filter((a) => a.id !== agentId);
  const missing = team.filter((id) => agents.data && !agents.data.some((a) => a.id === id));

  const toggle = (id: string) => {
    const nextTeam = team.includes(id) ? team.filter((x) => x !== id) : [...team, id];
    update({ ...draft, config: { ...config, sub_agent_ids: nextTeam } });
  };

  return (
    <Category icon={Users} tone="amber" title="Agents it can hand tasks to" hint="Pick up to five. It asks one when that agent's goal fits a part of the work better." badge={<Badge tone={team.length ? "amber" : "zinc"}>{team.length ? `${team.length} picked` : "None"}</Badge>}>
      {agents.isLoading ? (
        <div className="flex justify-center py-3"><Spinner className="h-4 w-4 text-zinc-400" /></div>
      ) : others.length === 0 ? (
        <p className="text-xs text-zinc-500">There are no other agents yet. Make another one, then come back to add it here.</p>
      ) : (
        <ul className="space-y-1.5">
          {others.map((a) => {
            const on = team.includes(a.id);
            const full = !on && team.length >= MAX_TEAM;
            return (
              <li key={a.id}>
                <button
                  type="button"
                  aria-pressed={on}
                  disabled={full}
                  onClick={() => toggle(a.id)}
                  className={cn(
                    "flex w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left text-xs transition disabled:opacity-40 cursor-pointer",
                    on ? "border-amber-300 bg-amber-50" : "border-zinc-200 hover:bg-zinc-50",
                  )}
                >
                  <span className={cn("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border", on ? "border-amber-500 bg-amber-500 text-white" : "border-zinc-300")}>
                    {on && <Check className="h-3 w-3" />}
                  </span>
                  <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-400" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-zinc-900">{a.name}</span>
                    <span className="block truncate text-[11px] text-zinc-500">{a.role}{a.goal ? ` · ${a.goal}` : ""}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {missing.length > 0 && (
        <p className="rounded-lg bg-amber-50 p-2 text-[11px] text-amber-800">
          {missing.length} picked agent{missing.length === 1 ? " was" : "s were"} deleted.{" "}
          <button type="button" className="font-medium underline cursor-pointer" onClick={() => update({ ...draft, config: { ...config, sub_agent_ids: team.filter((id) => !missing.includes(id)) } })}>
            Remove {missing.length === 1 ? "it" : "them"}
          </button>
        </p>
      )}
      <p className="rounded-lg bg-zinc-50 p-2.5 text-[11px] leading-relaxed text-zinc-500">
        A helper runs as the same person, with its own tools and knowledge, and can&apos;t hand tasks on again. It asks before data-changing tools by the stricter of the two agents&apos; rules.
      </p>
    </Category>
  );
}
