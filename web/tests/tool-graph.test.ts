import { describe, expect, it } from "vitest";

import { toolGraph } from "@/components/builder/tool-graph";

const base = {
  toolSubtitle: () => "",
  usedTools: [],
  token: "t",
  agent: { x: 0, y: 0 },
};

describe("agent canvas: tools grouped under their connector", () => {
  it("puts Connect on the connector node once, not on each tool", () => {
    const { nodes, edges } = toolGraph({
      ...base,
      toolIds: ["mcp:notion:search", "mcp:notion:create_page", "mcp:notion:update_page"],
      server: () => ({ name: "Notion", connected: false }),
    });
    const server = nodes.filter((n) => n.data.type === "server");
    expect(server).toHaveLength(1);
    expect(server[0].data.connect).toMatchObject({ serverId: "notion", serverName: "Notion" });
    expect(nodes.filter((n) => n.data.type === "tool").every((n) => !n.data.connect && n.data.problems.length === 0)).toBe(true);
    // agent → Notion → each tool
    expect(edges.map((e) => `${e.source}>${e.target}`)).toEqual([
      "agent>server:notion",
      "server:notion>tool:mcp:notion:search",
      "server:notion>tool:mcp:notion:create_page",
      "server:notion>tool:mcp:notion:update_page",
    ]);
  });

  it("offers no Connect once connected, or while still checking", () => {
    for (const connected of [true, undefined]) {
      const { nodes } = toolGraph({ ...base, toolIds: ["mcp:notion:search"], server: () => ({ name: "Notion", connected }) });
      expect(nodes.some((n) => n.data.connect)).toBe(false);
    }
  });

  it("hangs tools with no known connector straight off the agent", () => {
    const { nodes, edges } = toolGraph({ ...base, toolIds: ["web_search"], server: () => undefined });
    expect(nodes.map((n) => n.id)).toEqual(["tool:web_search"]);
    expect(edges[0]).toMatchObject({ source: "agent", target: "tool:web_search" });
  });
});
