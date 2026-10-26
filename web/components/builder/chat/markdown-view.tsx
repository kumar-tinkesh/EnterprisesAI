"use client";

import { memo, useMemo } from "react";

import { parseMarkdown, type Block, type Inline } from "@/lib/builder/markdown";

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
          case "link":
            return (
              <a key={i} href={n.href} target="_blank" rel="noopener noreferrer" className="break-words text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:text-indigo-800">
                <Inlines nodes={n.c} />
              </a>
            );
        }
      })}
    </>
  );
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
          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-lg border border-zinc-200">
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="bg-zinc-50">
                    <tr>
                      {b.head.map((c, n) => (
                        <th key={n} className="border-b border-zinc-200 px-2.5 py-1.5 font-semibold text-zinc-700">
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
