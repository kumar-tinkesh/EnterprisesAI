import { describe, expect, it } from "vitest";

import { addLive, emptyRunView, reduceRunEvent } from "@/lib/builder/run-state";

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

  it("gives way to the real answer and to a turn that went on to use tools", () => {
    let view = reduceRunEvent(emptyRunView, { type: "output_delta", ...d(1, 0, "Let me check") });
    expect(view.live?.text).toBe("Let me check");
    view = reduceRunEvent(view, { type: "agent_turn", node_id: "agent", turn: 1, tool_calls: ["search"] });
    expect(view.live).toBeNull();
    view = reduceRunEvent(view, { type: "output_delta", ...d(2, 0, "Done") });
    view = reduceRunEvent(view, { type: "output", text: "Done." });
    expect([view.live, view.output]).toEqual([null, "Done."]);
  });
});
