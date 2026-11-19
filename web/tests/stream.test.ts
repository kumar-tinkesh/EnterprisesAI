import { describe, expect, it } from "vitest";

import { addLive, emptyRunView, liveStatus, reduceRunEvent, thinkingText } from "@/lib/builder/run-state";

const d = (turn: number, at: number, text: string) => ({ node_id: "agent", turn, at, text });

describe("streamed answer text", () => {
  it("adds batches that line up", () => {
    let live = addLive(null, d(1, 0, "Hel"));
    live = addLive(live, d(1, 3, "lo"));
    expect(live?.text).toBe("Hello");
  });

  it("starts over at 0 (a new turn or a retried request) and waits out a gap", () => {
    const live = addLive(null, d(1, 0, "Hello"));
    expect(addLive(live, d(2, 0, "New"))?.text).toBe("New");
    expect(addLive(live, d(1, 9, "late"))?.text).toBe("Hello"); // joined late: no splicing
    expect(addLive(null, d(1, 4, "late"))).toBeNull();
  });

  it("keeps a tool-using turn's text in view (dimmed) until the next turn writes, then gives way to the answer", () => {
    let view = reduceRunEvent(emptyRunView, { type: "output_delta", ...d(1, 0, "Let me check") });
    expect(view.live?.text).toBe("Let me check");
    view = reduceRunEvent(view, { type: "agent_turn", node_id: "agent", turn: 1, tool_calls: ["search"] });
    expect(view.live).toEqual({ node: "agent", turn: 1, text: "Let me check", paused: true });
    view = reduceRunEvent(view, { type: "output_delta", ...d(2, 0, "Done") });
    expect(view.live).toEqual({ node: "agent", turn: 2, text: "Done" });
    view = reduceRunEvent(view, { type: "output", text: "Done." });
    expect([view.live, view.output]).toEqual([null, "Done."]);
  });
});

describe("the model's thinking", () => {
  const t = (turn: number, at: number, text: string, via?: string) => ({ type: "reasoning_delta" as const, ...d(turn, at, text), ...(via ? { via } : {}) });

  it("builds up a turn's thinking and keeps earlier turns' above the new one", () => {
    let view = reduceRunEvent(emptyRunView, t(1, 0, "Look "));
    view = reduceRunEvent(view, t(1, 5, "it up."));
    expect(thinkingText(view.thinking)).toBe("Look it up.");
    view = reduceRunEvent(view, t(2, 0, "Now answer."));
    expect(thinkingText(view.thinking)).toBe("Look it up.\n\nNow answer.");
    view = reduceRunEvent(view, t(2, 0, "Retried.")); // a retried request starts its turn over
    expect(thinkingText(view.thinking)).toBe("Look it up.\n\nRetried.");
  });

  it("leaves a sub-agent's thinking out and the answer untouched", () => {
    let view = reduceRunEvent(emptyRunView, t(1, 0, "theirs", "Helper"));
    expect(thinkingText(view.thinking)).toBe("");
    view = reduceRunEvent(view, t(1, 0, "mine"));
    view = reduceRunEvent(view, { type: "output_delta", ...d(1, 0, "Answer") });
    expect([thinkingText(view.thinking), view.live?.text]).toEqual(["mine", "Answer"]);
  });
});

describe("the live status line", () => {
  it("says what it's really doing, else leaves room for the thinking words", () => {
    expect(liveStatus(emptyRunView)).toBeNull();
    let view = reduceRunEvent(emptyRunView, { type: "tool_call", node_id: "agent", phase: "started", tool: "web__web_search" });
    expect(liveStatus(view)).toEqual({ text: "Using web search…", busy: true });
    view = reduceRunEvent(view, { type: "tool_call", node_id: "agent", phase: "finished", tool: "web__web_search" });
    expect(liveStatus(view)).toBeNull(); // back to thinking, not "web search done"
    view = reduceRunEvent(view, { type: "output_delta", ...d(2, 0, "Here") });
    expect(liveStatus(view)?.text).toBe("Writing…");
    expect(liveStatus({ ...view, status: "waiting" })).toEqual({ text: "Waiting for your decision", busy: false });
  });
});

describe("a workflow's thinking", () => {
  it("keeps each step's part and names the steps once more than one has thought", () => {
    let view = reduceRunEvent(emptyRunView, { type: "reasoning_delta", node_id: "r", turn: 1, at: 0, text: "Find facts." });
    view = reduceRunEvent(view, { type: "reasoning_delta", node_id: "w", turn: 1, at: 0, text: "Write it." });
    view = reduceRunEvent(view, { type: "reasoning_delta", node_id: "r", turn: 1, at: 11, text: " Then stop." });
    const name = (id: string) => ({ r: "Researcher", w: "Writer" })[id] ?? id;
    expect(thinkingText(view.thinking, name)).toBe("Researcher\nFind facts. Then stop.\n\nWriter\nWrite it.");
    expect(thinkingText(view.thinking.slice(0, 1), name)).toBe("Find facts. Then stop."); // one step: no name
  });
});
