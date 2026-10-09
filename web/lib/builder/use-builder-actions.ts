"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { draftKey } from "@/lib/builder/graph";
import type { Problem } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";

export type BuildMode = "agent" | "workflow";
export type BuildTarget = { kind: BuildMode; id: string };

/** Where an agent or workflow is edited: inside the AI Compiler page. */
export const editorHref = ({ kind, id }: BuildTarget) => `/user/agents?${kind}=${encodeURIComponent(id)}`;

/**
 * Create (with AI or blank) and delete agents/workflows; shared by the AI
 * Compiler and Projects. ``open`` shows the new one in place (the compiler
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
    mutationFn: async ({ mode, description }: { mode: BuildMode; description: string }) => {
      setError(null);
      if (mode === "workflow") {
        const draft = await builderApi.draftWorkflow(token, description);
        const wf = await builderApi.createWorkflow(token, { name: draft.name, description });
        window.sessionStorage.setItem(draftKey(wf.id), JSON.stringify(draft));
        return { kind: "workflow", id: wf.id } as BuildTarget;
      }
      const draft = await builderApi.draftAgent(token, description);
      const agent = await builderApi.createAgent(token, {
        name: draft.name, role: draft.role, goal: draft.goal, instructions: draft.instructions, config: draft.config,
      });
      const connect = draft.needs_connection.map((s) => s.server_name);
      window.sessionStorage.setItem(
        `builder.agent-notice.${agent.id}`,
        JSON.stringify({
          tone: connect.length ? "warn" : "ok",
          text: "Created by AI. Check it, then test it in the playground.",
          detail: connect.length ? [`Connect before running: ${connect.join(", ")}`] : undefined,
        }),
      );
      return { kind: "agent", id: agent.id } as BuildTarget;
    },
    onSuccess: (target) => (open ? open(target) : router.push(editorHref(target))),
    onError: fail,
  });

  const createBlank = useMutation({
    mutationFn: async (mode: BuildMode) => {
      setError(null);
      if (mode === "workflow") {
        const wf = await builderApi.createWorkflow(token, {
          name: "New workflow",
          nodes: [
            { id: "in", type: "input", position: { x: 0, y: 0 } },
            { id: "out", type: "output", position: { x: 600, y: 0 } },
          ],
          edges: [{ id: "e1", source: "in", target: "out" }],
        });
        return { kind: "workflow", id: wf.id } as BuildTarget;
      }
      const agent = await builderApi.createAgent(token, { name: "New agent", role: "Assistant", goal: "Describe what this agent does" });
      return { kind: "agent", id: agent.id } as BuildTarget;
    },
    onSuccess: (target) => (open ? open(target) : router.push(editorHref(target))),
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
