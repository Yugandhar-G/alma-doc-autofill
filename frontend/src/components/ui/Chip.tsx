import type { ReactNode } from "react";

import type { FindingSeverity, RunStatus } from "@/lib/matters/types";

export type ChipTone = "neutral" | "accent" | "info" | "warn" | "danger" | "good";

const TONES: Record<ChipTone, string> = {
  neutral: "border-line-strong bg-paper/70 text-ink-soft",
  accent: "border-accent/30 bg-accent-wash text-accent-deep",
  info: "border-accent/30 bg-accent-wash text-accent-deep",
  warn: "border-warn/30 bg-warn-wash text-warn",
  danger: "border-danger/30 bg-danger-wash text-danger",
  good: "border-good/30 bg-good-wash text-good",
};

type Props = {
  tone: ChipTone;
  children: ReactNode;
  /** Render a small leading dot in the tone color. */
  withDot?: boolean;
};

export function Chip({ tone, children, withDot = false }: Props) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] ${TONES[tone]}`}
    >
      {withDot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

// --- Status → tone/label maps (the ONE place these mappings live) -----------

const RUN_STATUS: Record<RunStatus, { tone: ChipTone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "info", label: "Running" },
  awaiting_input: { tone: "warn", label: "Awaiting input" },
  done: { tone: "good", label: "Done" },
  error: { tone: "danger", label: "Error" },
};

export function runStatusChip(status: RunStatus): { tone: ChipTone; label: string } {
  return RUN_STATUS[status] ?? { tone: "neutral", label: status };
}

export function RunStatusChip({ status }: { status: RunStatus }) {
  const { tone, label } = runStatusChip(status);
  return (
    <Chip tone={tone} withDot>
      {label}
    </Chip>
  );
}

const SEVERITY: Record<FindingSeverity, ChipTone> = {
  critical: "danger",
  warning: "warn",
  info: "info",
};

export function severityTone(severity: FindingSeverity): ChipTone {
  return SEVERITY[severity] ?? "neutral";
}
