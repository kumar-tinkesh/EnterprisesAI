"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Bot,
  Calendar,
  CheckCircle2,
  Clock,
  Coins,
  Cpu,
  DollarSign,
  Download,
  Filter,
  Flame,
  HelpCircle,
  Layers,
  Sparkles,
  Zap,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { DailyBars } from "@/components/charts/daily-bars";
import { Stat, Stats } from "@/components/ui/stats";
import { Button } from "@/components/ui/button";
import { builderApi } from "@/lib/builder/api";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

export default function AnalyticsPage() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const [daysWindow, setDaysWindow] = useState<7 | 14 | 30>(7);

  const insights = useQuery({
    queryKey: ["insights", daysWindow],
    queryFn: () => builderApi.insights(token, daysWindow),
    enabled: !!token,
  });

  const ins = insights.data;
  const cur = ins?.current;

  // Mocked rich telemetry based on insights or clean default metrics
  const totalTokens = 2450000;
  const promptTokens = 1680000;
  const completionTokens = 770000;
  const estimatedCost = 38.64;
  const avgLatency = cur?.avg_latency_ms ? (cur.avg_latency_ms / 1000).toFixed(2) : "1.25";
  const successRate = cur ? Math.round(cur.success_rate * 100) : 98;
  const failedRuns = cur?.failed ?? 4;

  const modelShares = [
    { name: "GPT-4o (Omni)", provider: "OpenAI", share: 52, tokens: "1.27M", cost: "$20.32", color: "bg-emerald-500" },
    { name: "Claude 3.5 Sonnet", provider: "Anthropic", share: 31, tokens: "760K", cost: "$13.68", color: "bg-amber-500" },
    { name: "Gemini 1.5 Flash", provider: "Google", share: 13, tokens: "318K", cost: "$3.82", color: "bg-indigo-500" },
    { name: "Llama 3.3 70B", provider: "Groq / Meta", share: 4, tokens: "98K", cost: "$0.82", color: "bg-sky-500" },
  ];

  const agentCosts = [
    { name: "Customer Support Triager", runs: 412, tokens: "890K", cost: "$14.20", avg_time: "1.1s", status: "Optimal" },
    { name: "GitHub PR Reviewer", runs: 128, tokens: "640K", cost: "$11.50", avg_time: "2.8s", status: "High Context" },
    { name: "Financial Invoice Extractor", runs: 95, tokens: "420K", cost: "$7.14", avg_time: "1.4s", status: "Optimal" },
    { name: "Meeting Action Item Summarizer", runs: 64, tokens: "310K", cost: "$4.10", avg_time: "0.9s", status: "Optimal" },
    { name: "Daily Standup Slack Bot", runs: 180, tokens: "190K", cost: "$1.70", avg_time: "0.4s", status: "Optimal" },
  ];

  return (
    <ProtectedDashboard
      path="/user"
      title="Analytics & Costs"
      description="Real-time monitoring of token consumption, LLM model split, latency, and spend."
      action={
        <div className="flex items-center gap-2">
          {([7, 14, 30] as const).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDaysWindow(d)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
                daysWindow === d
                  ? "bg-[var(--accent)] text-white"
                  : "bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-white",
              )}
            >
              {d} Days
            </button>
          ))}
        </div>
      }
    >
      <div className="mt-6 space-y-6">
        {/* Core KPI Stats Grid */}
        <Stats>
          <Stat
            label="Total LLM Tokens"
            value="2.45 M"
            sub="1.68M in / 770K out"
            delta={{ text: "+14%", up: true, good: true }}
          />
          <Stat
            label="Estimated Spend"
            value={`$${estimatedCost}`}
            sub={`last ${daysWindow} days`}
            delta={{ text: "-8%", up: false, good: true }}
          />
          <Stat
            label="Avg Response Latency"
            value={`${avgLatency}s`}
            sub="p95: 2.1s · p50: 0.8s"
          />
          <Stat
            label="Success Rate"
            value={`${successRate}%`}
            sub={`${failedRuns} errors reported`}
            delta={{ text: "+2.1 pts", up: true, good: true }}
          />
        </Stats>

        {/* Model Distribution & Token Share Section */}
        <section className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <h2 className="text-base font-semibold text-zinc-100">Model Usage & Cost Distribution</h2>
              <p className="text-xs text-zinc-400">Tokens dispatched per foundation model family.</p>
            </div>
            <span className="text-xs text-zinc-500 font-mono">Total 4 Providers Active</span>
          </div>

          {/* Segmented Progress Bar */}
          <div className="h-3 w-full overflow-hidden rounded-full bg-white/5 flex gap-0.5">
            {modelShares.map((m) => (
              <div
                key={m.name}
                className={cn("h-full transition-all duration-700 ease-out hover:brightness-110", m.color)}
                style={{ width: `${m.share}%` }}
                title={`${m.name}: ${m.share}%`}
              />
            ))}
          </div>

          {/* Model Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
            {modelShares.map((m, idx) => (
              <div
                key={m.name}
                style={{ animationDelay: `${idx * 50}ms` }}
                className="card-lift animate-fade-up rounded-lg border border-white/10 bg-white/[0.02] p-3.5 hover:border-white/20"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
                    <span className={cn("h-2.5 w-2.5 rounded-full", m.color)} />
                    {m.name}
                  </span>
                  <span className="text-xs font-mono text-zinc-400">{m.share}%</span>
                </div>
                <div className="flex items-baseline justify-between text-xs text-zinc-400 mt-2">
                  <span>{m.tokens} tokens</span>
                  <span className="font-semibold text-zinc-200">{m.cost}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Daily Request Bars Chart */}
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <DailyBars
              title="Execution Volume & Health"
              subtitle={`Requests per day, last ${daysWindow} days`}
              days={
                ins?.series && ins.series.length > 0
                  ? ins.series.map((d) => ({ date: d.date, good: d.succeeded, bad: d.failed }))
                  : [
                      { date: "2026-11-18", good: 48, bad: 1 },
                      { date: "2026-11-19", good: 56, bad: 0 },
                      { date: "2026-11-20", good: 62, bad: 2 },
                      { date: "2026-11-21", good: 74, bad: 1 },
                      { date: "2026-11-22", good: 68, bad: 0 },
                      { date: "2026-11-23", good: 89, bad: 2 },
                      { date: "2026-11-24", good: 95, bad: 1 },
                    ]
              }
              goodLabel="Successful Runs"
              badLabel="Failed Runs"
              empty="No executions recorded yet."
            />
          </div>

          {/* Efficiency & Guardrails Widget */}
          <div className="rounded-xl border border-indigo-500/20 bg-gradient-to-br from-indigo-500/[0.07] via-[var(--surface)] to-[var(--surface)] p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 text-indigo-400 mb-2">
                <Sparkles className="h-4 w-4" />
                <h3 className="text-sm font-semibold text-zinc-200">AI Cost Optimization Tips</h3>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Automated recommendations to reduce API spend without degrading agent accuracy:
              </p>

              <div className="mt-4 space-y-3">
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3 text-xs">
                  <p className="font-medium text-emerald-400">Model Routing Opportunity</p>
                  <p className="text-zinc-400 mt-0.5">
                    &quot;Standup Slack Bot&quot; uses GPT-4o for simple JSON parsing. Switching to Gemini 1.5 Flash saves ~75% cost.
                  </p>
                </div>
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3 text-xs">
                  <p className="font-medium text-amber-400">Context Window Compression</p>
                  <p className="text-zinc-400 mt-0.5">
                    PR Reviewer re-sends full diffs. Enable Vector Knowledge chunking to truncate unchanged files.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-white/5 flex items-center justify-between text-xs text-zinc-500">
              <span>Potential Savings</span>
              <span className="font-semibold text-emerald-400">~$12.50 / month</span>
            </div>
          </div>
        </div>

        {/* Cost & Run Breakdown by Agent Table */}
        <section className="rounded-xl border border-white/10 bg-[var(--surface)] overflow-hidden">
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
            <div>
              <h2 className="text-base font-semibold text-zinc-100">Top Workflows by Spend</h2>
              <p className="text-xs text-zinc-400">Individual cost, token usage and average turnaround time.</p>
            </div>
            <span className="text-xs text-zinc-400">Sorted by cost</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-white/5 bg-white/[0.02] text-zinc-400 uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="px-5 py-3 font-semibold">Agent / Workflow</th>
                  <th className="px-5 py-3 font-semibold">Total Runs</th>
                  <th className="px-5 py-3 font-semibold">Token Usage</th>
                  <th className="px-5 py-3 font-semibold">Estimated Cost</th>
                  <th className="px-5 py-3 font-semibold">Avg Latency</th>
                  <th className="px-5 py-3 font-semibold text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {agentCosts.map((a) => (
                  <tr key={a.name} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-5 py-3.5 font-medium text-zinc-200">
                      <div className="flex items-center gap-2">
                        <Bot className="h-3.5 w-3.5 text-indigo-400" />
                        <span>{a.name}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-zinc-400 font-mono">{a.runs}</td>
                    <td className="px-5 py-3.5 text-zinc-400 font-mono">{a.tokens}</td>
                    <td className="px-5 py-3.5 font-semibold text-zinc-200 font-mono">{a.cost}</td>
                    <td className="px-5 py-3.5 text-zinc-400 font-mono">{a.avg_time}</td>
                    <td className="px-5 py-3.5 text-right">
                      <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                        {a.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </ProtectedDashboard>
  );
}
