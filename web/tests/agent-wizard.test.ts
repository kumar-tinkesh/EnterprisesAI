import { beforeEach, describe, expect, it } from "vitest";

import {
  WIZARD_STEPS,
  accessOf,
  applyProfile,
  askFirstFor,
  blankAgent,
  groupByServer,
  guardrailsOn,
  matchingProfile,
  mergeConfig,
  presetToolIds,
  replaceServerTools,
  reviewIssues,
  stepIndex,
  toolList,
} from "@/lib/builder/agent-wizard";
import type { AgentProfile, DraftAgent, Risk } from "@/lib/builder/types";
import { useAgentWizard } from "@/stores/agent-wizard-store";

const PROFILES: AgentProfile[] = [
  { id: "quality", label: "Best quality", summary: "", config: { llm: { temperature: 0.3, max_output_tokens: 4000, reasoning_effort: "high" }, tools: { max_calls: 12 }, reliability: { retries: 2 }, response: { verbosity: "detailed" } } },
  { id: "balanced", label: "Balanced", summary: "", config: { llm: { temperature: 0.5, max_output_tokens: null, reasoning_effort: "auto" }, tools: { max_calls: 8 }, reliability: { retries: 1 }, response: { verbosity: "balanced" } } },
];

const TOOLS: { name: string; risk: Risk }[] = [
  { name: "search", risk: "read" },
  { name: "get", risk: "read" },
  { name: "create", risk: "edit" },
  { name: "remove", risk: "delete" },
];

const agent = (patch: Partial<DraftAgent> = {}): DraftAgent => ({ ...blankAgent(), name: "Helper", role: "Assistant", goal: "Help", ...patch });

describe("agent wizard: profiles", () => {
  it("merges sections key by key and replaces lists, like the backend", () => {
    const out = mergeConfig({ tool_ids: ["a"], response: { tone: "warm", verbosity: "balanced" } }, { tool_ids: ["b"], response: { verbosity: "concise" } });
    expect(out).toEqual({ tool_ids: ["b"], response: { tone: "warm", verbosity: "concise" } });
  });

  it("applies a profile without touching what it doesn't set, and recognises it afterwards", () => {
    const base = { ...blankAgent().config, tool_ids: ["mcp:s:t"], response: { tone: "warm" } };
    const config = applyProfile(base, PROFILES[0]);
    expect(config.tool_ids).toEqual(["mcp:s:t"]);
    expect(config.response).toEqual({ tone: "warm", verbosity: "detailed" });
    expect(matchingProfile(config, PROFILES)?.id).toBe("quality");
    // A hand edit makes it custom.
    expect(matchingProfile({ ...config, llm: { ...config.llm, temperature: 0.9 } }, PROFILES)).toBeNull();
    // "Model default" (null) matches an unset value.
    expect(matchingProfile(applyProfile(blankAgent().config, PROFILES[1]), PROFILES)?.id).toBe("balanced");
  });

  it("starts a blank agent asking before edits and deletes, on the given profile", () => {
    const blank = blankAgent(PROFILES[1]);
    expect(blank.config.approvals).toEqual({ read: false, edit: true, delete: true });
    expect(blank.config.tools?.max_calls).toBe(8);
    expect(blank.name).toBe("");
  });
});

describe("agent wizard: tools per server", () => {
  it("groups tools by server in first-seen order", () => {
    expect(groupByServer(["mcp:a:x", "mcp:b:y", "mcp:a:z"])).toEqual([
      { serverId: "a", toolIds: ["mcp:a:x", "mcp:a:z"] },
      { serverId: "b", toolIds: ["mcp:b:y"] },
    ]);
  });

  it("never puts delete tools in a preset", () => {
    expect(presetToolIds("s", TOOLS, "read")).toEqual(["mcp:s:search", "mcp:s:get"]);
    expect(presetToolIds("s", TOOLS, "readwrite")).toEqual(["mcp:s:search", "mcp:s:get", "mcp:s:create"]);
  });

  it("names the access a selection amounts to", () => {
    expect(accessOf("s", [], TOOLS)).toBe("none");
    expect(accessOf("s", ["mcp:s:get", "mcp:s:search", "mcp:other:x"], TOOLS)).toBe("read");
    expect(accessOf("s", presetToolIds("s", TOOLS, "readwrite"), TOOLS)).toBe("readwrite");
    expect(accessOf("s", ["mcp:s:search"], TOOLS)).toBe("custom");
    expect(accessOf("s", [...presetToolIds("s", TOOLS, "readwrite"), "mcp:s:remove"], TOOLS)).toBe("custom");
  });

  it("replaces one server's tools in place and leaves the others", () => {
    const ids = ["mcp:a:1", "mcp:b:1", "mcp:a:2", "mcp:c:1"];
    expect(replaceServerTools(ids, "b", ["mcp:b:2", "mcp:b:3"])).toEqual(["mcp:a:1", "mcp:b:2", "mcp:b:3", "mcp:a:2", "mcp:c:1"]);
    expect(replaceServerTools(ids, "a", [])).toEqual(["mcp:b:1", "mcp:c:1"]);
    expect(replaceServerTools(ids, "d", ["mcp:d:1"])).toEqual([...ids, "mcp:d:1"]);
    expect(replaceServerTools(ids, "c", ["mcp:c:1", "mcp:c:1"])).toEqual(ids);
  });
});

describe("agent wizard: review", () => {
  it("blocks on a missing name, role or goal and warns about the rest", () => {
    const issues = reviewIssues(agent({ name: " ", goal: "" }), { disconnected: [], knowledgeRecommended: false, needs: "" });
    expect(issues.map((i) => [i.level, i.step])).toEqual([["block", "identity"], ["block", "identity"]]);
  });

  it("warns about unconnected apps, missing tools and missing documents", () => {
    const draft = agent({ config: { ...blankAgent().config, guardrails: { groundedness: true } } });
    const issues = reviewIssues(draft, { disconnected: [{ serverId: "s1", name: "Gmail" }], knowledgeRecommended: true, needs: "read Gmail" });
    expect(issues.every((i) => i.level === "warn")).toBe(true);
    expect(issues.find((i) => i.serverId === "s1")?.message).toContain("Connect Gmail");
    expect(issues.map((i) => i.step)).toEqual(["abilities", "abilities", "abilities", "behaviour"]);
  });

  it("has nothing to say about a complete agent", () => {
    const draft = agent({ config: { ...blankAgent().config, tool_ids: ["mcp:s:t"], knowledge_base_ids: ["kb"] } });
    expect(reviewIssues(draft, { disconnected: [], knowledgeRecommended: true, needs: "x" })).toEqual([]);
  });

  it("describes safety checks, approvals and tool lists in plain words", () => {
    expect(guardrailsOn(undefined)).toEqual([]);
    expect(guardrailsOn({ injection: true, custom_rules: ["a"] })).toEqual(["blocks attempts to override its instructions", "follows 1 rule of yours"]);
    expect(askFirstFor(undefined)).toEqual(["changing data", "deleting anything"]);
    expect(askFirstFor({ read: true, edit: false, delete: false })).toEqual(["reading data"]);
    expect(toolList(["mcp:s:a", "mcp:s:b", "mcp:s:c", "mcp:s:d"])).toBe("a, b, c +1 more");
  });
});

describe("agent wizard: store", () => {
  beforeEach(() => useAgentWizard.getState().close());

  it("starts from a description, drafting straight away", () => {
    useAgentWizard.getState().start({ description: "summarise my inbox" });
    const s = useAgentWizard.getState();
    expect([s.open, s.autoGenerate, s.step, s.draft]).toEqual([true, true, "describe", null]);
  });

  it("starts blank on Identity and never auto-drafts", () => {
    useAgentWizard.getState().start({ blank: true });
    const s = useAgentWizard.getState();
    expect([s.autoGenerate, s.step, s.visited]).toEqual([false, "identity", ["describe", "identity"]]);
  });

  it("remembers visited steps once each, and a new start forgets the old draft", () => {
    const w = useAgentWizard.getState();
    w.start({ description: "x" });
    const session = useAgentWizard.getState().session;
    w.setDraft(agent());
    w.goTo("abilities");
    w.goTo("abilities");
    expect(useAgentWizard.getState().visited).toEqual(["describe", "abilities"]);
    w.start({});
    const s = useAgentWizard.getState();
    expect([s.draft, s.autoGenerate, s.session]).toEqual([null, false, session + 1]);
  });

  it("lists the steps in order", () => {
    expect(WIZARD_STEPS.map((s) => s.id)).toEqual(["describe", "identity", "abilities", "behaviour", "engine", "review"]);
    expect(stepIndex("review")).toBe(5);
  });
});
