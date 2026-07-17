import type { Metadata } from "next";
import Link from "next/link";

import { HealthBadge } from "@/components/flow/HealthBadge";
import { ScreenerFlow } from "@/components/screener/ScreenerFlow";

export const metadata: Metadata = {
  title: "Yunaki · O-1A / EB-1A Screener",
  description:
    "Answer a structured intake, add supporting documents, and watch the agent assess every USCIS criterion with audited citations. Decision support, not legal advice.",
};

export default function ScreenerPage() {
  return (
    <div className="flex flex-1 flex-col">
      <div aria-hidden className="h-1 bg-accent" />
      <header className="border-b border-line bg-surface/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-5 py-4">
          <div className="flex items-baseline gap-3">
            <Link
              href="/"
              className="font-display text-2xl tracking-tight transition-colors hover:text-accent-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Yunaki
            </Link>
            <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-soft">
              O-1A / EB-1A Visa Screener
            </span>
          </div>
          <span className="hidden rounded-full border border-line px-3 py-1 text-xs text-ink-soft sm:inline">
            Every verdict cited · nothing guessed
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-5 py-10">
        <ScreenerFlow />
      </main>

      <footer className="border-t border-line bg-surface/60">
        <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center justify-between gap-2 px-5 py-4">
          <HealthBadge />
          <p className="text-xs text-ink-faint">
            Documents are referenced by content hash only. Unverifiable citations are stripped —
            insufficient evidence is a finding, not a failure.
          </p>
        </div>
      </footer>
    </div>
  );
}
