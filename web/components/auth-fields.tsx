"use client";

import { forwardRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { Input, type InputProps } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export { Field, FieldError } from "@/components/form-fields";

/** Password box with a show/hide button (a tap target, so it works on touch too). */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, "type">>(
  ({ className, ...props }, ref) => {
    const [shown, setShown] = useState(false);
    return (
      <div className="relative" data-voice="off">
        <Input ref={ref} type={shown ? "text" : "password"} className={cn("pr-10", className)} {...props} />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? "Hide password" : "Show password"}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-[var(--text-subtle)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:text-[var(--text)]"
        >
          {shown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    );
  },
);
PasswordInput.displayName = "PasswordInput";

/** Thin rule with "or" in the middle, between Google and the email form. */
export function OrDivider() {
  return (
    <div className="flex items-center gap-3 text-xs text-[var(--text-subtle)]">
      <span className="h-px flex-1 bg-[var(--border)]" />
      or
      <span className="h-px flex-1 bg-[var(--border)]" />
    </div>
  );
}

/** The one error line under a form (server said no). */
export function FormError({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-wash)] px-3 py-2 text-sm text-[var(--danger)]">
      {children}
    </p>
  );
}
