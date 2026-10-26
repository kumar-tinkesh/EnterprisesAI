import { describe, expect, it } from "vitest";

import { parseInline, parseMarkdown, plainText } from "@/lib/builder/markdown";

describe("markdown: inline", () => {
  it("reads bold, italic, code and links", () => {
    expect(parseInline("a **b** *c* `d` [e](https://x.io)")).toEqual([
      { t: "text", v: "a " },
      { t: "strong", c: [{ t: "text", v: "b" }] },
      { t: "text", v: " " },
      { t: "em", c: [{ t: "text", v: "c" }] },
      { t: "text", v: " " },
      { t: "code", v: "d" },
      { t: "text", v: " " },
      { t: "link", href: "https://x.io", c: [{ t: "text", v: "e" }] },
    ]);
  });

  it("leaves snake_case names and unsafe links alone", () => {
    expect(parseInline("call send_email_now")).toEqual([{ t: "text", v: "call send_email_now" }]);
    expect(parseInline("[x](javascript:alert(1))")).toEqual([{ t: "text", v: "x)" }]);
  });

  it("links bare URLs without trailing punctuation", () => {
    expect(parseInline("see https://a.io/x.")).toEqual([
      { t: "text", v: "see " },
      { t: "link", href: "https://a.io/x", c: [{ t: "text", v: "https://a.io/x" }] },
      { t: "text", v: "." },
    ]);
  });
});

describe("markdown: blocks", () => {
  it("reads headings, lists, code, quotes and rules", () => {
    const blocks = parseMarkdown("# Title\n\n- one\n- two\n\n3. three\n4. four\n\n```py\nx = 1\n```\n\n> quoted\n\n---\nend");
    expect(blocks.map((b) => b.t)).toEqual(["h", "ul", "ol", "code", "quote", "hr", "p"]);
    expect(blocks[2]).toMatchObject({ t: "ol", start: 3 });
    expect(blocks[3]).toEqual({ t: "code", lang: "py", v: "x = 1" });
  });

  it("reads a table", () => {
    const [table] = parseMarkdown("| Name | Score |\n|---|:-:|\n| A | 1 |\n| B | 2 |");
    expect(table.t).toBe("table");
    if (table.t !== "table") return;
    expect(table.head.map((c) => c[0])).toEqual([{ t: "text", v: "Name" }, { t: "text", v: "Score" }]);
    expect(table.rows).toHaveLength(2);
  });

  it("keeps a paragraph's line breaks and gives back plain text", () => {
    const blocks = parseMarkdown("line one\nline **two**\n\n- a");
    expect(blocks[0]).toEqual({ t: "p", c: [{ t: "text", v: "line one\nline " }, { t: "strong", c: [{ t: "text", v: "two" }] }] });
    expect(plainText(blocks)).toBe("line one\nline two\n\n- a");
  });

  it("never throws on odd input", () => {
    for (const s of ["", "```", "|", "> ", "1.", "**", "[a](", "# "]) expect(() => parseMarkdown(s)).not.toThrow();
  });
});
