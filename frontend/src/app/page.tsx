import Link from "next/link";

import { AutofillFlow } from "@/components/flow/AutofillFlow";
import { HealthBadge } from "@/components/flow/HealthBadge";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      <div aria-hidden className="h-1 bg-accent" />
      <header className="border-b border-line bg-surface/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-5 py-4">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-2xl tracking-tight">Yunaki</span>
            <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-soft">
              G-28 Document Autofill
            </span>
          </div>
          <span className="hidden rounded-full border border-line px-3 py-1 text-xs text-ink-soft sm:inline">
            Runs locally · never submits or signs
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-5 py-10">
        <AutofillFlow />

        <Link
          href="/screener"
          className="group mt-12 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface px-5 py-4 shadow-[0_1px_2px_rgba(28,39,51,0.04)] transition-colors duration-150 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span>
            <span className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-deep">
              New
            </span>
            <span className="block font-display text-lg">O-1A / EB-1A Visa Screener</span>
            <span className="block text-xs text-ink-soft">
              Structured intake, evidence review, and criterion-by-criterion assessment — every
              verdict cited, nothing guessed.
            </span>
          </span>
          <span
            aria-hidden
            className="text-lg text-ink-faint transition-transform duration-150 group-hover:translate-x-1 group-hover:text-accent-deep"
          >
            →
          </span>
        </Link>
      </main>

      <footer className="border-t border-line bg-surface/60">
        <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center justify-between gap-2 px-5 py-4">
          <HealthBadge />
          <p className="text-xs text-ink-faint">
            Documents are referenced by content hash only. Unreadable fields stay blank — nothing
            is ever guessed.
          </p>
        </div>
      </footer>
    </div>
  );
}
