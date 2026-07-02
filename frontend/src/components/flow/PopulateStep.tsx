"use client";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { HUMAN_NOTE } from "@/lib/config";
import { countFilled, type G28Data, type PassportData } from "@/lib/types";

type Props = {
  passport: PassportData | null;
  g28: G28Data | null;
  isPopulating: boolean;
  error: string | null;
  onPopulate: () => void;
  onBack: () => void;
};

function ReadyCard({ label, count, skippedNote }: { label: string; count: number | null; skippedNote: string }) {
  return (
    <div className="flex-1 rounded-xl border border-line bg-surface px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">{label}</p>
      {count === null ? (
        <p className="mt-1 text-sm italic text-ink-faint">{skippedNote}</p>
      ) : (
        <>
          <p className="mt-1 font-display text-4xl">{count}</p>
          <p className="text-xs text-ink-soft">confirmed values ready to fill</p>
        </>
      )}
    </div>
  );
}

export function PopulateStep({ passport, g28, isPopulating, error, onPopulate, onBack }: Props) {
  const passportCount = passport
    ? countFilled(passport as unknown as Record<string, unknown>)
    : null;
  const g28Count = g28
    ? countFilled(g28.attorney as unknown as Record<string, unknown>) +
      countFilled(g28.eligibility as unknown as Record<string, unknown>) +
      countFilled(g28.beneficiary as unknown as Record<string, unknown>)
    : null;
  const hasAnything = (passportCount ?? 0) + (g28Count ?? 0) > 0;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Fill the form.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Your reviewed values are sent to the backend, re-validated against the same schemas, and
          typed into the target form field by field. Every field is then read back and compared —
          the report shows exactly what happened. {HUMAN_NOTE}
        </p>
      </header>

      <div className="flex flex-wrap gap-4">
        <ReadyCard
          label="Passport"
          count={passportCount}
          skippedNote="Skipped — passport fields stay untouched."
        />
        <ReadyCard
          label="Form G-28"
          count={g28Count}
          skippedNote="Skipped — G-28 fields stay untouched."
        />
      </div>

      {!hasAnything && (
        <Banner tone="warn">
          There are no confirmed values to fill. Go back and upload at least one document, or type
          verified values into the review tables.
        </Banner>
      )}

      {error && <Banner tone="danger">{error}</Banner>}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onBack} disabled={isPopulating}>
          Back to review
        </Button>
        <Button onClick={onPopulate} disabled={!hasAnything} isBusy={isPopulating}>
          {isPopulating ? "Filling the form…" : "Populate the form"}
        </Button>
      </footer>
    </section>
  );
}
