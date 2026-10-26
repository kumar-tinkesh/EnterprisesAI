"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import { vendorApi } from "@/lib/api";
import { AgentEditor } from "@/components/builder/agent-editor";
import { WorkflowEditor } from "@/components/builder/workflow-editor";
import { editorHref, type BuildTarget } from "@/lib/builder/use-builder-actions";
import { AgentWizardHost } from "@/components/builder/agent-wizard/agent-wizard";
import { useAgentWizard } from "@/stores/agent-wizard-store";
import BuilderHome from "./agent-canvas";

/** ?agent=<id> / ?workflow=<id> -> the agent or workflow open in the editor. */
function targetFromUrl(): BuildTarget | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const agent = params.get("agent");
  const workflow = params.get("workflow");
  return workflow ? { kind: "workflow", id: workflow } : agent ? { kind: "agent", id: agent } : null;
}

export default function UserAgentsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";

  // An agent or workflow open in place of the start page — built here, or opened
  // from Executions. Kept in the URL so reload / the back button behave.
  const [editing, setEditing] = useState<BuildTarget | null>(null);
  useEffect(() => {
    const target = targetFromUrl();
    // A saved wizard left open (it lives in sessionStorage) would cover the
    // editor this link asked for; it's done, so close it.
    if (target && useAgentWizard.getState().createdId) useAgentWizard.getState().close();
    setEditing(target);
    const onPop = () => setEditing(targetFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const openEditor = (target: BuildTarget) => {
    window.history.pushState(null, "", editorHref(target));
    setEditing(target);
  };
  const closeEditor = () => {
    window.history.pushState(null, "", "/user/agents");
    setEditing(null);
  };

  // Only to say "connect an app first" on the start page.
  const { data: catalog } = useQuery({
    queryKey: ["catalog", accessToken, ""],
    queryFn: () => vendorApi.getCatalog(accessToken),
    enabled: !!accessToken,
  });
  const hasAnyConnectedServer = !catalog || catalog.servers.some((s) => s.connected);

  if (editing) {
    return (
      <ProtectedDashboard path="/user" title="AI Compiler" description="Build and test an agent or workflow" fullBleed>
        {editing.kind === "workflow" ? (
          <WorkflowEditor key={editing.id} id={editing.id} onBack={closeEditor} onExit={closeEditor} onOpen={openEditor} onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })} />
        ) : (
          <AgentEditor key={editing.id} id={editing.id} onBack={closeEditor} onExit={closeEditor} onOpen={openEditor} />
        )}
        <AgentWizardHost onOpen={openEditor} />
      </ProtectedDashboard>
    );
  }

  return (
    <ProtectedDashboard path="/user" title="AI Compiler" description="Describe an agent or a workflow and it's built for you.">
      <BuilderHome hasAnyConnectedServer={hasAnyConnectedServer} onOpen={openEditor} />
      <AgentWizardHost onOpen={openEditor} />
    </ProtectedDashboard>
  );
}
