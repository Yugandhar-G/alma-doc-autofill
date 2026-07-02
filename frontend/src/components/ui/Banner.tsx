import type { ReactNode } from "react";

type Tone = "danger" | "warn" | "good" | "info";

const TONES: Record<Tone, string> = {
  danger: "border-danger/30 bg-danger-wash text-danger",
  warn: "border-warn/30 bg-warn-wash text-warn",
  good: "border-good/30 bg-good-wash text-good",
  info: "border-accent/30 bg-accent-wash text-accent-deep",
};

export function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={`rounded-lg border px-4 py-3 text-sm leading-relaxed ${TONES[tone]}`}
    >
      {children}
    </div>
  );
}
