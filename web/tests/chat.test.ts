import { describe, expect, it } from "vitest";

import { AGENT_STARTERS, ago, dayLabel, formatCost, formatDuration, formatTokens, hueOf, initials, runDurationMs, startersFor, trailSummary } from "@/lib/builder/chat";
import type { RunToolCall } from "@/lib/builder/types";

const call = (patch: Partial<RunToolCall>): RunToolCall => ({
  id: "c", node_id: null, tool_name: "s__t", risk: "read", status: "succeeded", arguments: {}, result_preview: null, is_error: false, duration_ms: 10, ...patch,
});

describe("chat helpers", () => {
  it("makes avatars and durations", () => {
    expect(initials("web search agent")).toBe("WS");
    expect(initials("  ")).toBe("?");
    expect(hueOf("x")).toBe(hueOf("x"));
    expect([formatDuration(250), formatDuration(4200), formatDuration(125_000)]).toEqual(["250 ms", "4.2 s", "2m 5s"]);
    expect(runDurationMs({ started_at: "2026-10-12T10:00:00Z", finished_at: "2026-10-12T10:00:03.5Z" })).toBe(3500);
    expect(runDurationMs({ started_at: "2026-10-12T10:00:00Z", finished_at: null })).toBeNull();
  });

  it("labels days and ages", () => {
    const now = new Date("2026-10-12T12:00:00");
    expect(dayLabel("2026-10-12T08:00:00", now)).toBe("Today");
    expect(dayLabel("2026-10-11T08:00:00", now)).toBe("Yesterday");
    const t = now.getTime();
    expect([ago(null, t), ago(new Date(t - 30_000).toISOString(), t), ago(new Date(t - 5 * 60_000).toISOString(), t), ago(new Date(t - 3 * 3_600_000).toISOString(), t)]).toEqual(["", "just now", "5 min ago", "3 h ago"]);
  });

  it("sums up what a run did", () => {
    expect(trailSummary({ tool_calls: [] })).toBeNull();
    expect(trailSummary({ tool_calls: [call({})] })).toBe("Used 1 tool");
    expect(trailSummary({ tool_calls: [call({}), call({ status: "failed", is_error: true }), call({ status: "declined" })] })).toBe("Used 3 tools · 1 failed · 1 declined");
  });

  it("formats cost and tokens", () => {
    expect([formatCost(null), formatCost(0), formatCost(0.00421), formatCost(0.125), formatCost(12.5)]).toEqual([null, "$0", "$0.0042", "$0.125", "$12.50"]);
    expect([formatTokens(950), formatTokens(1500), formatTokens(12_400), formatTokens(3_000_000)]).toEqual(["950", "1.5k", "12k", "3M"]);
  });

  it("uses an agent's own starters when it has them", () => {
    expect(startersFor(["  Order status ", ""])).toEqual([{ label: "Order status", prompt: "Order status" }]);
    expect(startersFor([])).toBe(AGENT_STARTERS);
  });
});
