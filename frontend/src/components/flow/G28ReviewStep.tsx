"use client";

import type { FieldValue } from "@/components/review/FieldRow";
import { SectionCard } from "@/components/review/SectionCard";
import { Button } from "@/components/ui/Button";
import { ATTORNEY_FIELDS, BENEFICIARY_FIELDS, ELIGIBILITY_FIELDS } from "@/lib/fields";
import { fieldWarning } from "@/lib/review";
import type { G28Data } from "@/lib/types";

type G28Section = keyof G28Data;

type Props = {
  g28: G28Data;
  warnings: Record<string, string>;
  onChange: (next: G28Data) => void;
  onBack: () => void;
  onConfirm: () => void;
};

export function G28ReviewStep({ g28, warnings, onChange, onBack, onConfirm }: Props) {
  const setField = (section: G28Section, key: string, value: FieldValue) => {
    onChange({ ...g28, [section]: { ...g28[section], [key]: value } });
  };

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Is the G-28 data correct?</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Check each part against the uploaded form. Unchecked boxes and blank lines arrive as{" "}
          <em>not set</em> and are skipped during filling — never guessed.
        </p>
      </header>

      <SectionCard
        partLabel="Part 1"
        title="Attorney or accredited representative"
        fields={ATTORNEY_FIELDS}
        values={g28.attorney as unknown as Record<string, FieldValue>}
        warningFor={(key) => fieldWarning(warnings, key, "attorney")}
        onField={(key, v) => setField("attorney", key, v)}
      />
      <SectionCard
        partLabel="Part 2"
        title="Eligibility of the representative"
        fields={ELIGIBILITY_FIELDS}
        values={g28.eligibility as unknown as Record<string, FieldValue>}
        warningFor={(key) => fieldWarning(warnings, key, "eligibility")}
        onField={(key, v) => setField("eligibility", key, v)}
      />
      <SectionCard
        partLabel="Part 3"
        title="Client (beneficiary)"
        fields={BENEFICIARY_FIELDS}
        values={g28.beneficiary as unknown as Record<string, FieldValue>}
        warningFor={(key) => fieldWarning(warnings, key, "beneficiary")}
        onField={(key, v) => setField("beneficiary", key, v)}
      />

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onBack}>
          Back to upload
        </Button>
        <Button onClick={onConfirm}>Looks correct — continue to fill</Button>
      </footer>
    </section>
  );
}
