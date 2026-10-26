import { describe, expect, it } from "vitest";

import { answerJsonText, answerToJson } from "@/lib/builder/answer-json";

const ANSWER = [
  "## Rohit Sharma",
  "",
  "Rohit Sharma is a **leading** Indian cricketer. See [Cricbuzz](https://cricbuzz.com).",
  "",
  "- Three ODI double centuries",
  "- Record 264 against Sri Lanka",
  "",
  "1. Test captain in 2022",
  "2. Five IPL titles",
  "",
  "| Format | Runs |",
  "| --- | --- |",
  "| ODI | 11000 |",
  "",
  "```python",
  "print('hi')",
  "```",
].join("\n");

describe("answer as JSON", () => {
  it("keeps every part of the answer, in order, as written", () => {
    expect(answerToJson(ANSWER, { question: "tell me about rohit sharma", sources: ["Wikipedia"] })).toEqual({
      question: "tell me about rohit sharma",
      answer: [
        { type: "heading", level: 2, text: "Rohit Sharma" },
        { type: "paragraph", text: "Rohit Sharma is a leading Indian cricketer. See Cricbuzz (https://cricbuzz.com)." },
        { type: "list", ordered: false, items: ["Three ODI double centuries", "Record 264 against Sri Lanka"] },
        { type: "list", ordered: true, items: ["Test captain in 2022", "Five IPL titles"] },
        { type: "table", columns: ["Format", "Runs"], rows: [{ Format: "ODI", Runs: "11000" }] },
        { type: "code", language: "python", code: "print('hi')" },
      ],
      sources: ["Wikipedia"],
    });
  });

  it("gives the same JSON every time", () => {
    const first = answerJsonText(ANSWER, { question: "q" });
    for (let i = 0; i < 5; i++) expect(answerJsonText(ANSWER, { question: "q" })).toBe(first);
  });

  it("is one paragraph for a plain answer, with nothing added", () => {
    expect(answerToJson("Just one line.")).toEqual({ answer: [{ type: "paragraph", text: "Just one line." }] });
  });

  it("names empty or repeated table headings by position", () => {
    const json = answerToJson("| A | A |  |\n|---|---|---|\n| 1 | 2 | 3 |");
    expect(json.answer[0]).toEqual({ type: "table", columns: ["A", "column_2", "column_3"], rows: [{ A: "1", column_2: "2", column_3: "3" }] });
  });
});
