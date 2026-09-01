"use client";

import {
  Rocket,
  Bot,
  Brain,
  FolderKanban,
  Zap,
  ArrowRight,
} from "lucide-react";
import { useRouter } from "next/navigation";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";

const QUICK_ACTIONS = [
  {
    icon: Bot,
    title: "Agent Builder",
    desc: "Describe an agent in natural language — the AI Compiler picks your authorized MCP servers and LangGraph runs it.",
    color: "#6366f1",
    bg: "#eef2ff",
    href: "/user/agents",
  },
  {
    icon: Brain,
    title: "Knowledge Base",
    desc: "Upload documents, connect data sources, and build RAG pipelines. (coming soon)",
    color: "#8b5cf6",
    bg: "#f5f3ff",
  },
  {
    icon: FolderKanban,
    title: "Projects",
    desc: "Organise agents into projects with shared context and workflows. (coming soon)",
    color: "#0ea5e9",
    bg: "#f0f9ff",
  },
  {
    icon: Zap,
    title: "Executions",
    desc: "Monitor agent runs, view logs, and inspect tool-call traces. (coming soon)",
    color: "#f59e0b",
    bg: "#fffbeb",
  },
];

export default function UserDashboard() {
  const user = useAuthStore((s) => s.user);
  const displayName = user?.full_name || "there";
  const router = useRouter();

  return (
    <ProtectedDashboard
      path="/user"
      title="My Workspace"
      description="Your AI workspace — build, deploy, and run agents."
    >
      {/* Hero banner */}
      <div
        className="mt-6 rounded-xl p-6"
        style={{
          background:
            "linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a78bfa 100%)",
        }}
      >
        <div className="flex items-center gap-3 text-white">
          <Rocket className="h-7 w-7" />
          <div>
            <h2 className="text-lg font-bold">Welcome, {displayName}!</h2>
            <p className="mt-0.5 text-sm text-indigo-100">
              Everything you need to build AI agents — all in one place.
            </p>
          </div>
        </div>
      </div>

      {/* Quick-action cards */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {QUICK_ACTIONS.map((a) => (
          <button
            key={a.title}
            onClick={() => a.href && router.push(a.href)}
            className="group rounded-xl border border-zinc-200 bg-white p-5 text-left transition-all hover:shadow-md hover:-translate-y-0.5"
            style={{ borderColor: "transparent" }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.borderColor = a.color + "40")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.borderColor = "transparent")
            }
          >
            <div className="flex items-start gap-4">
              <div
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                style={{ backgroundColor: a.bg }}
              >
                <a.icon className="h-5 w-5" style={{ color: a.color }} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-zinc-900">{a.title}</h3>
                  <ArrowRight className="h-4 w-4 text-zinc-300 transition-transform group-hover:translate-x-1 group-hover:text-zinc-500" />
                </div>
                <p className="mt-1 text-sm leading-relaxed text-zinc-500">
                  {a.desc}
                </p>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Stats */}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatCard label="Agents" value="0" accent="#6366f1" />
        <StatCard label="Executions today" value="0" accent="#0ea5e9" />
        <StatCard label="Knowledge docs" value="0" accent="#8b5cf6" />
      </div>

      {/* Activity feed */}
      <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-zinc-900">Recent activity</h2>
        <p className="mt-2 text-sm text-zinc-400">
          No activity yet — create your first agent to get started.
        </p>
      </div>
    </ProtectedDashboard>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: string;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <p className="text-sm font-medium text-zinc-500">{label}</p>
      <p className="mt-1 text-3xl font-bold" style={{ color: accent }}>
        {value}
      </p>
    </div>
  );
}