import * as React from "react";

import { cn } from "@/lib/utils";

export function Alert({
  children,
  className,
  variant = "default",
}: {
  children: React.ReactNode;
  className?: string;
  variant?: "default" | "destructive";
}) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg border p-4 text-sm",
        variant === "destructive"
          ? "border-red-300 bg-red-50 text-red-800"
          : "border-zinc-300 bg-zinc-50 text-zinc-800",
        className,
      )}
    >
      {children}
    </div>
  );
}