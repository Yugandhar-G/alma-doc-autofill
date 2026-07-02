import { AutofillFlow } from "@/components/flow/AutofillFlow";
import { HealthBadge } from "@/components/flow/HealthBadge";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      <div aria-hidden className="h-1 bg-accent" />
      <header className="border-b border-line bg-surface/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-5 py-4">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-2xl tracking-tight">Alma</span>
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
