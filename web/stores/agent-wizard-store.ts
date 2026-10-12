"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { WizardStepId } from "@/lib/builder/agent-wizard";
import type { AgentInsights, DraftAgent, ToolCandidate } from "@/lib/builder/types";

/**
 * The guided agent setup, open over the AI Compiler. Nothing is saved to the
 * server until Create, so the draft lives here — in sessionStorage, so a
 * reload (or an OAuth redirect) in the middle of it doesn't lose it.
 */
export interface WizardData {
  open: boolean;
  /** Bumped on every start, so per-session component state starts fresh. */
  session: number;
  description: string;
  /** Start drafting from ``description`` as soon as the wizard mounts. */
  autoGenerate: boolean;
  step: WizardStepId;
  visited: WizardStepId[];
  draft: DraftAgent | null;
  insights: AgentInsights | null;
  /** What we know about each tool (server, risk, why it was picked), by tool id. */
  toolMeta: Record<string, ToolCandidate>;
  /** Why the suggested guardrails were chosen (set when they're applied). */
  guardrailReason: string | null;
  createdId: string | null;
}

interface WizardState extends WizardData {
  start: (opts: { description?: string; blank?: boolean }) => void;
  set: (patch: Partial<WizardData>) => void;
  goTo: (step: WizardStepId) => void;
  setDraft: (draft: DraftAgent) => void;
  close: () => void;
}

const EMPTY: WizardData = {
  open: false,
  session: 0,
  description: "",
  autoGenerate: false,
  step: "describe",
  visited: [],
  draft: null,
  insights: null,
  toolMeta: {},
  guardrailReason: null,
  createdId: null,
};

export const useAgentWizard = create<WizardState>()(
  persist(
    (set, get) => ({
      ...EMPTY,
      start: ({ description = "", blank = false }) =>
        set({
          ...EMPTY,
          open: true,
          session: get().session + 1,
          description,
          autoGenerate: !blank && description.trim().length >= 3,
          step: blank ? "identity" : "describe",
          visited: blank ? ["describe", "identity"] : ["describe"],
        }),
      set: (patch) => set(patch),
      goTo: (step) => set((s) => ({ step, visited: s.visited.includes(step) ? s.visited : [...s.visited, step] })),
      setDraft: (draft) => set({ draft }),
      close: () => set({ ...EMPTY, session: get().session }),
    }),
    {
      name: "builder.agent-wizard",
      storage: createJSONStorage(() => sessionStorage),
      partialize: ({ start: _s, set: _set, goTo: _g, setDraft: _d, close: _c, ...data }) => ({ ...data, autoGenerate: false }),
    },
  ),
);
