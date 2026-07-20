"use client";

import { useMemo, useState } from "react";

import type { FieldValue } from "@/components/review/FieldRow";
import { SectionCard } from "@/components/review/SectionCard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ATTORNEY_FIELDS, BENEFICIARY_FIELDS, ELIGIBILITY_FIELDS, PASSPORT_FIELDS } from "@/lib/fields";
import { fieldWarning, g28FromEnvelope, passportFromEnvelope, warningsByField } from "@/lib/review";
import type { ExtractionEnvelope, G28Data, PassportData } from "@/lib/types";

/**
 * Interrupt panel for the autofill `extraction_review` kind. Reuses the exact
 * review primitives the legacy flow uses (SectionCard + FieldRow + field
 * descriptors + envelope mappers) so edits re-validate through the same schema
 * shapes on resume. Nulls stay null end-to-end.
 *
 * payload = { passport: ExtractionEnvelope | null, g28: ExtractionEnvelope | null }
 */
type Props = {
  payload: Record<string, unknown>;
  onSubmit: (resumePayload: { passport: PassportData | null; g28: G28Data | null }) => void;
  isSubmitting?: boolean;
  submitError?: string | null;
};

function asEnvelope(value: unknown): ExtractionEnvelope | null {
  if (value === null || value === undefined) return null;
  return value as ExtractionEnvelope;
}

export function ExtractionReviewPanel({ payload, onSubmit, isSubmitting, submitError }: Props) {
  const passportEnv = asEnvelope(payload.passport);
  const g28Env = asEnvelope(payload.g28);

  const [passport, setPassport] = useState<PassportData>(() => passportFromEnvelope(passportEnv));
  const [g28, setG28] = useState<G28Data>(() => g28FromEnvelope(g28Env));

  const passportWarnings = useMemo(() => warningsByField(passportEnv), [passportEnv]);
  const g28Warnings = useMemo(() => warningsByField(g28Env), [g28Env]);

  const hasPassport = passportEnv !== null;
  const hasG28 = g28Env !== null;

  const setG28Field = (section: keyof G28Data, key: string, value: FieldValue) => {
    setG28((prev) => ({ ...prev, [section]: { ...prev[section], [key]: value } }));
  };

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm leading-relaxed text-ink-soft">
        Check every value against the document. Empty fields could not be read and are skipped when
        the form is filled — type a value only if you can verify it. Nothing is ever guessed.
      </p>

      {hasPassport && (
        <SectionCard
          partLabel="Passport"
          title="Machine-readable data page"
          subtitle="Dates are ISO (YYYY-MM-DD); country and nationality are full English names."
          fields={PASSPORT_FIELDS}
          values={passport as unknown as Record<string, FieldValue>}
          warningFor={(key) => passportWarnings[key]}
          onField={(key, v) => setPassport((prev) => ({ ...prev, [key]: v }))}
        />
      )}

      {hasG28 && (
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

      {submitError && <Banner tone="danger">{submitError}</Banner>}

      <div className="flex justify-end border-t border-line pt-4">
        <Button
          isBusy={isSubmitting}
          onClick={() =>
            onSubmit({ passport: hasPassport ? passport : null, g28: hasG28 ? g28 : null })
          }
        >
          Approve and populate the form
        </Button>
      </div>
    </div>
  );
}
