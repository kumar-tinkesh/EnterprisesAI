import { Bot, Network } from "lucide-react";

import { cn } from "@/lib/utils";

const SIZES = { sm: "h-7 w-7 [&>svg]:h-3.5 [&>svg]:w-3.5", md: "h-8 w-8 [&>svg]:h-4 [&>svg]:w-4", lg: "h-14 w-14 rounded-xl [&>svg]:h-6 [&>svg]:w-6" };

/** What an agent or a workflow looks like everywhere: its type's icon on a quiet tile. */
export function TypeIcon({ kind, size = "md", live, className }: { kind: "agent" | "workflow"; size?: keyof typeof SIZES; live?: boolean; className?: string }) {
  const Icon = kind === "workflow" ? Network : Bot;
  return (
    <span
      aria-hidden
      className={cn("flex shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-zinc-100 text-zinc-700", SIZES[size], live && "animate-pulse", className)}
    >
      <Icon />
    </span>
  );
}
