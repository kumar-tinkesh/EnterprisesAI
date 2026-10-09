"use client";

import { useParams, useRouter } from "next/navigation";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AgentEditor } from "@/components/builder/agent-editor";

export default function AgentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  return (
    <ProtectedDashboard path="/user" title="Agent" description="Build and test an agent" fullBleed>
      <AgentEditor id={id} onBack={() => router.push("/user/projects")} />
    </ProtectedDashboard>
  );
}
