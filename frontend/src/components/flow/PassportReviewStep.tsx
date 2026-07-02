"use client";

import type { FieldValue } from "@/components/review/FieldRow";
import { SectionCard } from "@/components/review/SectionCard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { PASSPORT_FIELDS } from "@/lib/fields";
import type { PassportData } from "@/lib/types";

type Props = {
  passport: PassportData;
  warningFor: (key: string) => string | undefined;
  /** Note about which fields the back side contributed, when any. */
  backMergeNote: string | null;
  onChange: (next: PassportData) => void;
  onBack: () => void;
  onConfirm: () => void;
};

export function PassportReviewStep({
  passport,
  warningFor,
  backMergeNote,
  onChange,
  onBack,
  onConfirm,
}: Props) {
  const missing = PASSPORT_FIELDS.filter((f) => passport[f.key] === null).length;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Is the passport data correct?</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Check every value against the passport itself. Empty fields could not be read and will be
          skipped when the form is filled — type a value only if you can verify it on the document.
        </p>
      </header>

      {missing > 0 && (
        <Banner tone="info">
          {missing} field{missing === 1 ? " was" : "s were"} not readable. That is normal for many
          passports — nothing is ever guessed to fill the gap.
        </Banner>
      )}

      <div className="flex flex-col gap-2">
        <SectionCard
          partLabel="Passport"
          title="Machine-readable data page"
          subtitle="Dates are ISO (YYYY-MM-DD); country and nationality are full English names."
          fields={PASSPORT_FIELDS}
          values={passport as unknown as Record<string, FieldValue>}
          warningFor={warningFor}
          onField={(key, v) => onChange({ ...passport, [key]: v })}
        />
        {backMergeNote && (
          <p className="px-1 text-xs italic leading-relaxed text-ink-soft">{backMergeNote}</p>
        )}
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onBack}>
          Back to uploads
        </Button>
        <Button onClick={onConfirm}>Looks correct — continue to the G-28</Button>
      </footer>
    </section>
  );
}
