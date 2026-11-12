"use client";

import { memo, useMemo } from "react";

import { parseMarkdown, shortUrl, type Block, type Inline } from "@/lib/builder/markdown";
import { cn } from "@/lib/utils";

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((n, i) => {
        switch (n.t) {
          case "text":
            return <span key={i}>{n.v}</span>;
          case "code":
            return (
              <code key={i} className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[0.85em] text-zinc-800">
                {n.v}
              </code>
            );
          case "strong":
            return (
              <strong key={i} className="font-semibold text-zinc-900">
                <Inlines nodes={n.c} />
              </strong>
            );
          case "em":
            return (
              <em key={i}>
                <Inlines nodes={n.c} />
              </em>
            );
          case "link": {
            // A bare URL reads as its short form; the full one is on hover and in the link.
            const bare = n.c.length === 1 && n.c[0].t === "text" && n.c[0].v === n.href;
            return (
              <a key={i} href={n.href} title={bare ? n.href : undefined} target="_blank" rel="noopener noreferrer" className="break-words text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:text-indigo-800">
                {bare ? shortUrl(n.href) : <Inlines nodes={n.c} />}
              </a>
            );
          }
        }
      })}
    </>
  );
}

/** A cell with something in it (an empty one is left off a card). */
function hasText(nodes: Inline[] | undefined): boolean {
  return !!nodes?.some((n) => (n.t === "text" || n.t === "code" ? n.v.trim() : true));
}

const HEADING = ["", "text-lg font-semibold", "text-base font-semibold", "text-sm font-semibold", "text-sm font-semibold text-zinc-700"];

function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.t) {
          case "p":
            return (
              <p key={i} className="whitespace-pre-wrap break-words">
                <Inlines nodes={b.c} />
              </p>
            );
          case "h":
            return (
              <p key={i} role="heading" aria-level={b.level + 2} className={`${HEADING[b.level]} mt-4 text-zinc-900`}>
                <Inlines nodes={b.c} />
              </p>
            );
          case "code":
            return (
              <pre key={i} className="overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-relaxed text-zinc-800">
                <code>{b.v}</code>
              </pre>
            );
          case "ul":
            return (
              <ul key={i} className="list-disc space-y-1 pl-5 marker:text-zinc-400">
                {b.items.map((it, n) => (
                  <li key={n} className="whitespace-pre-wrap break-words pl-0.5">
                    <Inlines nodes={it} />
                  </li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} start={b.start} className="list-decimal space-y-1 pl-5 marker:text-zinc-500">
                {b.items.map((it, n) => (
                  <li key={n} className="whitespace-pre-wrap break-words pl-0.5">
                    <Inlines nodes={it} />
                  </li>
                ))}
              </ol>
            );
          case "quote":
            return (
              <blockquote key={i} className="space-y-2 border-l-2 border-zinc-300 pl-3 text-zinc-600">
                <Blocks blocks={b.c} />
              </blockquote>
            );
          case "table": {
            // A wide table (5+ columns) reads as one card per row where the answer is narrow (a phone, a side panel).
            const wide = b.head.length >= 5;
            const grid = (
              <div className={cn("overflow-x-auto rounded-lg border border-zinc-200", wide && "hidden @xl:block")}>
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="bg-zinc-50">
                    <tr>
                      {b.head.map((c, n) => (
                        <th key={n} className="whitespace-nowrap border-b border-zinc-200 px-2.5 py-1.5 font-semibold text-zinc-700">
                          <Inlines nodes={c} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, n) => (
                      <tr key={n} className="border-b border-zinc-100 last:border-0">
                        {r.map((c, k) => (
                          <td key={k} className="px-2.5 py-1.5 align-top text-zinc-700">
                            <Inlines nodes={c} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
            if (!wide) return <div key={i}>{grid}</div>;
            return (
              <div key={i} className="@container">
                {grid}
                <ul className="space-y-2 @xl:hidden">
                  {b.rows.map((r, n) => (
                    <li key={n} className="rounded-lg border border-zinc-200 p-3 text-xs">
                      {/* The first two cells (e.g. score and company) head the card; the rest are labelled lines. */}
                      <p className="text-sm font-medium text-zinc-900">
                        <Inlines nodes={r[0] ?? []} />
                        {hasText(r[1]) && <span className="text-zinc-500"> · </span>}
                        <Inlines nodes={r[1] ?? []} />
                      </p>
                      <dl className="mt-1.5 space-y-1">
                        {r.slice(2).map((c, k) =>
                          hasText(c) ? (
                            <div key={k} className="flex gap-2">
                              <dt className="w-24 shrink-0 text-zinc-500"><Inlines nodes={b.head[k + 2] ?? []} /></dt>
                              <dd className="min-w-0 break-words text-zinc-700"><Inlines nodes={c} /></dd>
                            </div>
                          ) : null,
                        )}
                      </dl>
                    </li>
                  ))}
                </ul>
              </div>
            );
          }
          case "hr":
            return <hr key={i} className="border-zinc-200" />;
        }
      })}
    </>
  );
}

/** A model's answer, formatted. Never renders HTML from the text. */
export const MarkdownView = memo(function MarkdownView({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return (
    <div className="space-y-3 text-sm leading-relaxed text-zinc-800">
      <Blocks blocks={blocks} />
    </div>
  );
});
