import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-hover)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] cursor-pointer disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]",
        outline: "border border-[var(--border-strong)] bg-transparent text-[var(--text)] hover:bg-[var(--hover)]",
        ghost: "bg-transparent text-[var(--text-muted)] hover:bg-[var(--hover)] hover:text-[var(--text)]",
        danger: "bg-[var(--danger-wash)] text-[var(--danger)] hover:bg-[rgb(239_68_68/0.24)]",
      },
      size: {
        default: "h-9 px-4",
        sm: "h-8 px-3",
        lg: "h-10 px-6",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        type={type ?? "button"}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
