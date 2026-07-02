"use client";

import { useMemo } from "react";

import type { FieldValue } from "@/components/review/FieldRow";
import { SectionCard } from "@/components/review/SectionCard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { nameConflicts } from "@/lib/coherence";
import {
  ATTORNEY_FIELDS,
  BENEFICIARY_FIELDS,
  ELIGIBILITY_FIELDS,
  PASSPORT_FIELDS,
} from "@/lib/fields";
import { fieldWarning, warningsByField } from "@/lib/review";
import type { ExtractionEnvelope, G28Data, PassportData } from "@/lib/types";

type G28Section = keyof G28Data;

type Props = {
  passportEnvelope: ExtractionEnvelope | null;
  g28Envelope: ExtractionEnvelope | null;
  passport: PassportData | null;
  g28: G28Data | null;
  isPopulating: boolean;
  populateError: string | null;
  onPassportChange: (next: PassportData) => void;
  onG28Change: (next: G28Data) => void;
  onPopulate: () => void;
  onRestart: () => void;
};

const DOC_LABEL: Record<string, string> = {
  passport: "a passport",
  g28: "a Form G-28",
  other: "a different kind of document",
  unknown: "unrecognizable",
};

function MismatchBanner({ envelope, slotName }: { envelope: ExtractionEnvelope; slotName: string }) {
  const detected = DOC_LABEL[envelope.document_type_detected] ?? envelope.document_type_detected;
  return (
    <Banner tone="danger">
      <strong className="font-semibold">Wrong document in the {slotName} slot.</strong> The file
      was detected as {detected}, so its fields were not extracted. Go back and upload the correct
      document, or fill the fields below by hand only if you can verify them.
    </Banner>
  );
}

export function ReviewStage({
  passportEnvelope,
  g28Envelope,
  passport,
  g28,
  isPopulating,
  populateError,
  onPassportChange,
  onG28Change,
  onPopulate,
  onRestart,
}: Props) {
  const passportWarnings = useMemo(() => warningsByField(passportEnvelope), [passportEnvelope]);
  const g28Warnings = useMemo(() => warningsByField(g28Envelope), [g28Envelope]);
  const conflicts = useMemo(() => nameConflicts(passport, g28), [passport, g28]);

  const passportMismatch =
    passportEnvelope !== null && passportEnvelope.document_type_detected !== "passport";
  const g28Mismatch = g28Envelope !== null && g28Envelope.document_type_detected !== "g28";

  const setG28Field = (section: G28Section, key: string, value: FieldValue) => {
    if (!g28) return;
    onG28Change({ ...g28, [section]: { ...g28[section], [key]: value } });
  };

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Review before anything is filled.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Check every value against the source documents. Empty fields were not readable and will
          be skipped — type a value only if you can verify it. Your edits are re-validated by the
          backend before the form is touched.
        </p>
      </header>

      {passportMismatch && passportEnvelope && (
        <MismatchBanner envelope={passportEnvelope} slotName="passport" />
      )}
      {g28Mismatch && g28Envelope && <MismatchBanner envelope={g28Envelope} slotName="G-28" />}

      {conflicts.length > 0 && (
        <Banner tone="warn">
          <strong className="font-semibold">The passport and G-28 disagree on the client&rsquo;s name.</strong>
          <ul className="mt-1 list-inside list-disc">
            {conflicts.map((c) => (
              <li key={c.label}>
                {c.label}: passport says <span className="font-mono">&ldquo;{c.passportValue}&rdquo;</span>,
                G-28 beneficiary says <span className="font-mono">&ldquo;{c.g28Value}&rdquo;</span>
              </li>
            ))}
          </ul>
          Confirm these belong to the same person before populating.
        </Banner>
      )}

      {g28 && (
        <>
          <SectionCard
            partLabel="Part 1"
            title="Attorney or accredited representative"
            fields={ATTORNEY_FIELDS}
            values={g28.attorney as unknown as Record<string, FieldValue>}
            warningFor={(key) => fieldWarning(g28Warnings, key, "attorney")}
            onField={(key, v) => setG28Field("attorney", key, v)}
          />
          <SectionCard
            partLabel="Part 2"
            title="Eligibility of the representative"
            fields={ELIGIBILITY_FIELDS}
            values={g28.eligibility as unknown as Record<string, FieldValue>}
            warningFor={(key) => fieldWarning(g28Warnings, key, "eligibility")}
            onField={(key, v) => setG28Field("eligibility", key, v)}
          />
          <SectionCard
            partLabel="Part 3"
            title="Client (beneficiary)"
            fields={BENEFICIARY_FIELDS}
            values={g28.beneficiary as unknown as Record<string, FieldValue>}
            warningFor={(key) => fieldWarning(g28Warnings, key, "beneficiary")}
            onField={(key, v) => setG28Field("beneficiary", key, v)}
          />
        </>
      )}

      {passport && (
        <SectionCard
          partLabel="Passport"
          title="Machine-readable data page"
          subtitle="Feeds the client identity fields in Part 3 of the form. Dates are ISO (YYYY-MM-DD)."
          fields={PASSPORT_FIELDS}
          values={passport as unknown as Record<string, FieldValue>}
          warningFor={(key) => fieldWarning(passportWarnings, key)}
          onField={(key, v) => onPassportChange({ ...passport, [key]: v })}
        />
      )}

      {!g28 && (
        <Banner tone="info">
          No G-28 was uploaded — the attorney, eligibility, and beneficiary fields will be left
          untouched on the form.
        </Banner>
      )}
      {!passport && (
        <Banner tone="info">
          No passport was uploaded — the passport-sourced identity fields will be left untouched
          on the form.
        </Banner>
      )}

      {populateError && <Banner tone="danger">{populateError}</Banner>}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onRestart} disabled={isPopulating}>
          Start over
        </Button>
        <Button onClick={onPopulate} isBusy={isPopulating}>
          {isPopulating ? "Filling the form…" : "Populate the form"}
        </Button>
      </footer>
    </section>
  );
}
