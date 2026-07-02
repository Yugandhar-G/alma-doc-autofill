"use client";

import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  isBusy?: boolean;
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium " +
  "transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-deep active:bg-accent-deep",
  secondary:
    "border border-line-strong bg-surface text-ink hover:border-accent hover:text-accent-deep",
  ghost: "text-ink-soft hover:text-ink hover:bg-line/40",
};

export function Button({
  variant = "primary",
  isBusy = false,
  disabled,
  children,
  className = "",
  ...rest
}: Props) {
  return (
    <button
      type="button"
      disabled={disabled || isBusy}
      className={`${BASE} ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {isBusy && (
        <span
          aria-hidden
          className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
}
