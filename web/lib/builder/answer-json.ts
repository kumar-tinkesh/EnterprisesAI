import { parseMarkdown, type Block, type Inline } from "@/lib/builder/markdown";

/**
 * An answer as JSON, made from its own text by code, not by a model: the same
 * answer always gives the same JSON, and it holds exactly what the answer says,
 * in its order — each paragraph, heading, list, table and code block becomes
 * one entry of ``answer``.
 */
export type AnswerJson = {
  question?: string;
  answer: AnswerPart[];
  sources?: string[];
};

export type AnswerPart =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "code"; language: string | null; code: string }
  | { type: "quote"; content: AnswerPart[] }
  | { type: "table"; columns: string[]; rows: Record<string, string>[] };

/** Inline markdown as plain text; a link keeps its address, "text (https://…)". */
function inline(nodes: Inline[]): string {
  return nodes
    .map((n) => {
      if (n.t === "text" || n.t === "code") return n.v;
      const text = inline(n.c);
      return n.t === "link" && n.href !== text ? `${text} (${n.href})` : text;
    })
    .join("");
}

function parts(blocks: Block[]): AnswerPart[] {
  const out: AnswerPart[] = [];
  for (const b of blocks) {
    switch (b.t) {
      case "p":
        out.push({ type: "paragraph", text: inline(b.c) });
        break;
      case "h":
        out.push({ type: "heading", level: b.level, text: inline(b.c) });
        break;
      case "ul":
      case "ol":
        out.push({ type: "list", ordered: b.t === "ol", items: b.items.map(inline) });
        break;
      case "code":
        out.push({ type: "code", language: b.lang || null, code: b.v });
        break;
      case "quote":
        out.push({ type: "quote", content: parts(b.c) });
        break;
      case "table": {
        // Each row keyed by its column's heading; an empty or repeated heading gets its position instead.
        const seen = new Set<string>();
        const columns = b.head.map((cell, i) => {
          const name = inline(cell).trim();
          const key = name && !seen.has(name) ? name : `column_${i + 1}`;
          seen.add(key);
          return key;
        });
        out.push({
          type: "table",
          columns,
          rows: b.rows.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i] ? inline(row[i]) : ""]))),
        });
        break;
      }
      case "hr":
        break;
    }
  }
  return out;
}

export function answerToJson(text: string, extra: { question?: string; sources?: string[] } = {}): AnswerJson {
  // Keys in a fixed order: question, answer, sources.
  return {
    ...(extra.question?.trim() ? { question: extra.question.trim() } : {}),
    answer: parts(parseMarkdown(text)),
    ...(extra.sources?.length ? { sources: extra.sources } : {}),
  };
}

/** ``answerToJson``, pretty-printed for showing and copying. */
export function answerJsonText(text: string, extra: { question?: string; sources?: string[] } = {}): string {
  return JSON.stringify(answerToJson(text, extra), null, 2);
}
