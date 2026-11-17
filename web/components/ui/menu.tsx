"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";

/** ``divided``: a line above it, to start a new group. */
export type MenuItem = { label: string; onClick: () => void; danger?: boolean; checked?: boolean; divided?: boolean };

const WIDTH = 208;
const GAP = 4;
const EDGE = 8;

/**
 * A ⋯ button (or the given ``trigger``) with a small list of labelled actions.
 * The list opens on top of the page (a portal), so a scrolling or clipped
 * container around the button can't cut it off; it flips up when there's no
 * room below.
 */
export function Menu({ label, items, trigger, triggerClassName }: { label: string; items: MenuItem[]; trigger?: React.ReactNode; triggerClassName?: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const alignStart = !!trigger;

  // Under the button (a text trigger lines up on the left, ⋯ on the right), inside the screen; up when there's no room below.
  const place = useCallback(() => {
    if (!button.current || !list.current) return;
    const r = button.current.getBoundingClientRect();
    const h = list.current.offsetHeight;
    const below = r.bottom + GAP;
    setPos({
      left: Math.max(EDGE, Math.min(alignStart ? r.left : r.right - WIDTH, window.innerWidth - WIDTH - EDGE)),
      top: below + h > window.innerHeight - EDGE && r.top - GAP - h > EDGE ? r.top - GAP - h : below,
    });
  }, [alignStart]);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !button.current?.contains(e.target as Node) && !list.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    // Pinned to the screen, so it follows the button when anything around it scrolls.
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setPos(null);
          setOpen((v) => !v);
        }}
        className={triggerClassName ?? "shrink-0 rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"}
      >
        {trigger ?? <MoreHorizontal className="h-4 w-4" />}
      </button>
      {open &&
        createPortal(
          <div
            ref={list}
            role="menu"
            aria-label={label}
            style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, width: WIDTH, visibility: pos ? "visible" : "hidden" }}
            className="fixed z-[60] rounded-lg border border-zinc-200 bg-[var(--surface-raised)] p-1 shadow-lg"
          >
            {items.map((it) => (
              <div key={it.label} className={cn(it.divided && "mt-1 border-t border-zinc-200 pt-1")}>
                <button
                  type="button"
                  role={it.checked === undefined ? "menuitem" : "menuitemradio"}
                  aria-checked={it.checked}
                  onClick={() => {
                    setOpen(false);
                    it.onClick();
                  }}
                  className={cn("flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-zinc-100 cursor-pointer", it.danger ? "text-red-600" : "text-zinc-700")}
                >
                  {it.label}
                  {it.checked && <Check className="h-4 w-4 shrink-0 text-zinc-900" />}
                </button>
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
