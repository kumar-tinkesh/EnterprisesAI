"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { draftKey } from "@/lib/builder/graph";
import type { Problem } from "@/lib/builder/types";
import { useAgentWizard } from "@/stores/agent-wizard-store";
import { useAuthStore } from "@/stores/auth-store";

export type BuildMode = "agent" | "workflow";
export type BuildTarget = { kind: BuildMode; id: string };

/** Where an agent or workflow is edited: inside the AI Compiler page. */
export const editorHref = ({ kind, id }: BuildTarget) => `/user/agents?${kind}=${encodeURIComponent(id)}`;

/**
 * Create (with AI or blank) and delete agents/workflows; shared by the AI
 * Compiler and Executions. A new agent opens the guided setup
 * (components/builder/agent-wizard) instead of being saved straight away. ``open`` shows the new one in place (the compiler
 * page); without it the browser goes to the compiler page with it open.
 */
export function useBuilderActions({ open }: { open?: (target: BuildTarget) => void } = {}) {
  const router = useRouter();
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const fail = (err: unknown) => {
    const problems = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
    setError(problems.length ? problems.map((p) => p.message).join(" ") : err instanceof Error ? err.message : "Something went wrong.");
  };

  const createWithAi = useMutation({
    mutationFn: async ({ mode, description }: { mode: BuildMode; description: string }): Promise<BuildTarget | null> => {
      setError(null);
      if (mode === "agent") {
        // Agents go through the guided setup: it drafts the agent from the
        // description and nothing is saved until the person creates it there.
        useAgentWizard.getState().start({ description });
        return null;
      }
      const draft = await builderApi.draftWorkflow(token, description);
      const wf = await builderApi.createWorkflow(token, { name: draft.name, description });
      window.sessionStorage.setItem(draftKey(wf.id), JSON.stringify(draft));
      return { kind: "workflow", id: wf.id };
    },
    onSuccess: (target) => target && (open ? open(target) : router.push(editorHref(target))),
    onError: fail,
  });

  const createBlank = useMutation({
    mutationFn: async (mode: BuildMode): Promise<BuildTarget | null> => {
      setError(null);
      if (mode === "agent") {
        // A new agent is the guided setup, from its first (Describe) step.
        useAgentWizard.getState().start({});
        return null;
      }
      const wf = await builderApi.createWorkflow(token, {
        name: "New workflow",
        nodes: [
          { id: "in", type: "input", position: { x: 0, y: 0 } },
          { id: "out", type: "output", position: { x: 600, y: 0 } },
        ],
        edges: [{ id: "e1", source: "in", target: "out" }],
      });
      return { kind: "workflow", id: wf.id };
    },
    // The guided setup lives on the AI Compiler page.
    onSuccess: (target) => (target ? (open ? open(target) : router.push(editorHref(target))) : !open && router.push("/user/agents")),
    onError: fail,
  });

  const remove = useMutation({
    mutationFn: ({ kind, id }: { kind: BuildMode; id: string }) => (kind === "agent" ? builderApi.deleteAgent(token, id) : builderApi.deleteWorkflow(token, id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["builder-agents"] });
      void queryClient.invalidateQueries({ queryKey: ["builder-workflows"] });
    },
    onError: fail,
  });

  return { createWithAi, createBlank, remove, error, setError };
}
