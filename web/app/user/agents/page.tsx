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
import { ProjectDetail, type DetailTab } from "@/components/builder/project-detail";
import BuilderHome from "./agent-canvas";

/** ?agent=<id> / ?workflow=<id> -> the agent or workflow open in the visual canvas editor. */
function targetFromUrl(): BuildTarget | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const agent = params.get("agent");
  const workflow = params.get("workflow");
  return workflow ? { kind: "workflow", id: workflow } : agent ? { kind: "agent", id: agent } : null;
}

/** ?workspace=<kind>:<id> or ?chat=<kind>:<id> -> dedicated workspace / playground. */
function workspaceFromUrl(): { target: BuildTarget; tab: DetailTab } | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("workspace") || params.get("chat");
  const tabParam = params.get("tab") as DetailTab;
  const tab = tabParam && ["overview", "chat", "simulate", "health"].includes(tabParam) ? tabParam : "chat";
  if (!raw) return null;
  const [kind, id] = raw.split(":");
  if ((kind === "agent" || kind === "workflow") && id) {
    return { target: { kind, id }, tab };
  }
  return null;
}

export default function UserAgentsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";

  // Visual Canvas Editor Mode
  const [editing, setEditing] = useState<BuildTarget | null>(null);

  // Dedicated Agent Workspace / Playground Mode
  const [workspace, setWorkspace] = useState<{ target: BuildTarget; tab: DetailTab } | null>(null);

  useEffect(() => {
    const editTarget = targetFromUrl();
    const wsTarget = workspaceFromUrl();

    if (editTarget) {
      if (useAgentWizard.getState().createdId) useAgentWizard.getState().close();
      setEditing(editTarget);
      setWorkspace(null);
    } else if (wsTarget) {
      setWorkspace(wsTarget);
      setEditing(null);
    } else {
      setEditing(null);
      setWorkspace(null);
    }

    const onPop = () => {
      setEditing(targetFromUrl());
      setWorkspace(workspaceFromUrl());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const openEditor = (target: BuildTarget) => {
    window.history.pushState(null, "", editorHref(target));
    setEditing(target);
    setWorkspace(null);
  };

  const closeEditor = () => {
    window.history.pushState(null, "", "/user/agents");
    setEditing(null);
  };

  const openWorkspace = (target: BuildTarget, tab: DetailTab = "chat") => {
    const url = new URL(window.location.href);
    url.searchParams.delete("agent");
    url.searchParams.delete("workflow");
    url.searchParams.set("workspace", `${target.kind}:${target.id}`);
    url.searchParams.set("tab", tab);
    window.history.pushState(null, "", url.toString());
    setWorkspace({ target, tab });
    setEditing(null);
  };

  const setWorkspaceTab = (tab: DetailTab) => {
    if (!workspace) return;
    openWorkspace(workspace.target, tab);
  };

  const closeWorkspace = () => {
    window.history.pushState(null, "", "/user/agents");
    setWorkspace(null);
  };

  // Check app server connection
  const { data: catalog } = useQuery({
    queryKey: ["catalog", accessToken, ""],
    queryFn: () => vendorApi.getCatalog(accessToken),
    enabled: !!accessToken,
  });
  const hasAnyConnectedServer = !catalog || catalog.servers.some((s) => s.connected);

  // 1. Canvas Visual Graph Editor View
  if (editing) {
    return (
      <ProtectedDashboard path="/user" title="Editor" description="Build and test an agent or workflow" fullBleed>
        {editing.kind === "workflow" ? (
          <WorkflowEditor
            key={editing.id}
            id={editing.id}
            onBack={closeEditor}
            onExit={closeEditor}
            onChat={() => openWorkspace(editing, "chat")}
            onOpen={openEditor}
            onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })}
          />
        ) : (
          <AgentEditor
            key={editing.id}
            id={editing.id}
            onBack={closeEditor}
            onExit={closeEditor}
            onChat={() => openWorkspace(editing, "chat")}
            onOpen={openEditor}
          />
        )}
        <AgentWizardHost onOpen={openEditor} />
      </ProtectedDashboard>
    );
  }

  // 2. Dedicated Agent Workspace / Playground (Approach B)
  if (workspace) {
    return (
      <ProtectedDashboard
        path="/user"
        title="Agent Workspace"
        description="Interact, test, and monitor your agent."
        fullBleed
      >
        <ProjectDetail
          key={`${workspace.target.kind}:${workspace.target.id}`}
          target={workspace.target}
          token={accessToken}
          tab={workspace.tab}
          onTab={setWorkspaceTab}
          onClose={closeWorkspace}
          onOpenCanvas={() => openEditor(workspace.target)}
          onSwitchTarget={(newTarget) => openWorkspace(newTarget, workspace.tab)}
          isWorkspace
        />
        <AgentWizardHost onOpen={openEditor} />
      </ProtectedDashboard>
    );
  }

  // 3. Main Catalog / Hub View
  return (
    <ProtectedDashboard
      path="/user"
      title="Agents & Workflows"
      description="Build, manage, and run your AI agents and automated workflows."
      fullBleed
    >
      <BuilderHome
        hasAnyConnectedServer={hasAnyConnectedServer}
        onOpen={openEditor}
        onOpenWorkspace={openWorkspace}
      />
      <AgentWizardHost onOpen={openEditor} />
    </ProtectedDashboard>
  );
}
