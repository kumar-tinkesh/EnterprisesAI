"use client";

import { useParams, useRouter } from "next/navigation";

import ProtectedDashboard from "@/components/protected-dashboard";
import { WorkflowEditor } from "@/components/builder/workflow-editor";

export default function WorkflowEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  return (
    <ProtectedDashboard path="/user" title="Workflow" description="Build and test a workflow" fullBleed>
      <WorkflowEditor id={id} onBack={() => router.push("/user/projects")} onSwitch={(workflowId) => router.push(`/user/builder/workflows/${workflowId}`)} />
    </ProtectedDashboard>
  );
}
