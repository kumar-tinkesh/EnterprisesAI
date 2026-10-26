/**
 * A small Markdown reader for model answers: the blocks and inline marks
 * models actually write (headings, lists, tables, code, quotes, bold, italic,
 * code spans, links). It returns a tree; the chat renders it as React
 * elements, so nothing is ever injected as HTML. Covered by
 * tests/markdown.test.ts.
 */

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] };

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; level: 1 | 2 | 3 | 4; c: Inline[] }
  | { t: "code"; lang: string; v: string }
  | { t: "ul" | "ol"; items: Inline[][]; start?: number }
  | { t: "quote"; c: Block[] }
  | { t: "table"; head: Inline[][]; rows: Inline[][][] }
  | { t: "hr" };

const SAFE_HREF = /^(https?:\/\/|mailto:)/i;

/** Inline marks, left to right; anything unmatched stays text. */
export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const push = (node: Inline) => {
    const last = out[out.length - 1];
    if (node.t === "text" && last?.t === "text") last.v += node.v;
    else out.push(node);
  };
  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i);
    let m: RegExpMatchArray | null;
    if ((m = rest.match(/^`([^`]+)`/))) {
      push({ t: "code", v: m[1] });
    } else if ((m = rest.match(/^\*\*([^*]+?)\*\*/)) || (m = rest.match(/^__([^_]+?)__/))) {
      push({ t: "strong", c: parseInline(m[1]) });
    } else if ((m = rest.match(/^\*([^*\s][^*]*?)\*/))) {
      push({ t: "em", c: parseInline(m[1]) });
    } else if ((i === 0 || /\W/.test(text[i - 1])) && (m = rest.match(/^_([^_\s][^_]*?)_(?!\w)/))) {
      // Only at a word's start, so snake_case names stay as they are.
      push({ t: "em", c: parseInline(m[1]) });
    } else if ((m = rest.match(/^\[([^\]]+)\]\(([^)\s]+)\)/))) {
      if (SAFE_HREF.test(m[2])) push({ t: "link", href: m[2], c: parseInline(m[1]) });
      else push({ t: "text", v: m[1] });
    } else if ((m = rest.match(/^https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"]/))) {
      push({ t: "link", href: m[0], c: [{ t: "text", v: m[0] }] });
    } else {
      // Plain text up to the next character that could start a mark.
      const next = rest.slice(1).search(/[`*_[h]/);
      const len = next < 0 ? rest.length : next + 1;
      push({ t: "text", v: rest.slice(0, len) });
      i += len;
      continue;
    }
    i += m[0].length;
  }
  return out;
}

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => parseInline(c.trim()));

const isTableRule = (line: string) => line.includes("-") && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(src: string): Block[] {
  const lines = (src || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ t: "p", c: parseInline(para.join("\n")) });
    para = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m: RegExpMatchArray | null;

    if ((m = line.match(/^\s*(```|~~~)\s*([\w+-]*)\s*$/))) {
      flush();
      const fence = m[1];
      const body: string[] = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith(fence); i++) body.push(lines[i]);
      blocks.push({ t: "code", lang: m[2], v: body.join("\n") });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    if ((m = line.match(/^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/))) {
      flush();
      blocks.push({ t: "h", level: Math.min(m[1].length, 4) as 1 | 2 | 3 | 4, c: parseInline(m[2]) });
      continue;
    }
    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flush();
      blocks.push({ t: "hr" });
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      flush();
      const head = cells(line);
      const rows: Inline[][][] = [];
      for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim(); i++) rows.push(cells(lines[i]));
      i--;
      blocks.push({ t: "table", head, rows });
      continue;
    }
    if (/^\s{0,3}>/.test(line)) {
      flush();
      const body: string[] = [];
      for (; i < lines.length && /^\s{0,3}>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s{0,3}>\s?/, ""));
      i--;
      blocks.push({ t: "quote", c: parseMarkdown(body.join("\n")) });
      continue;
    }
    const bullet = /^\s{0,3}[-*+]\s+(.*)$/;
    const numbered = /^\s{0,3}(\d{1,9})[.)]\s+(.*)$/;
    if (bullet.test(line) || numbered.test(line)) {
      flush();
      const ordered = numbered.test(line);
      const re = ordered ? numbered : bullet;
      const items: string[] = [];
      const start = ordered ? Number(line.match(numbered)![1]) : undefined;
      for (; i < lines.length; i++) {
        const l = lines[i];
        const hit = l.match(re);
        if (hit) items.push(ordered ? hit[2] : hit[1]);
        else if (l.trim() && /^\s{2,}\S/.test(l) && items.length) items[items.length - 1] += `\n${l.trim()}`;
        else if (!l.trim() && i + 1 < lines.length && re.test(lines[i + 1])) continue;
        else break;
      }
      i--;
      blocks.push({ t: ordered ? "ol" : "ul", items: items.map(parseInline), ...(ordered && start !== 1 ? { start } : {}) });
      continue;
    }
    para.push(line);
  }
  flush();
  return blocks;
}

/** Plain text of an answer (for copying), without the marks. */
export function plainText(blocks: Block[]): string {
  const inline = (c: Inline[]): string => c.map((n) => (n.t === "text" || n.t === "code" ? n.v : inline(n.c))).join("");
  return blocks
    .map((b) => {
      switch (b.t) {
        case "p":
        case "h":
          return inline(b.c);
        case "code":
          return b.v;
        case "ul":
        case "ol":
          return b.items.map((it, n) => `${b.t === "ol" ? `${(b.start ?? 1) + n}.` : "-"} ${inline(it)}`).join("\n");
        case "quote":
          return plainText(b.c);
        case "table":
          return [b.head, ...b.rows].map((r) => r.map(inline).join("\t")).join("\n");
        case "hr":
          return "";
      }
    })
    .join("\n\n");
}
