"use client";

import { FieldRow, type FieldValue } from "@/components/review/FieldRow";
import type { FieldDef } from "@/lib/fields";

type Props = {
  /** Echo of the real form, e.g. "Part 1". */
  partLabel: string;
  title: string;
  subtitle?: string;
  fields: FieldDef[];
  values: Record<string, FieldValue>;
  warningFor: (key: string) => string | undefined;
  onField: (key: string, value: FieldValue) => void;
};

export function SectionCard({
  partLabel,
  title,
  subtitle,
  fields,
  values,
  warningFor,
  onField,
}: Props) {
  const presentCount = fields.filter((f) => {
    const v = values[f.key];
    return v !== null && v !== "";
  }).length;

  return (
    <section className="overflow-hidden rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line bg-paper/50 px-5 py-3.5">
        <div className="flex items-baseline gap-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-deep">
            {partLabel}
          </span>
          <h3 className="font-display text-lg">{title}</h3>
        </div>
        <span className="text-xs text-ink-faint">
          {presentCount} of {fields.length} fields have values
        </span>
      </header>
      {subtitle && <p className="border-b border-line px-5 py-2 text-xs text-ink-soft">{subtitle}</p>}
      <div className="divide-y divide-line px-5 py-1">
        {fields.map((def) => (
          <FieldRow
            key={def.key}
            def={def}
            value={values[def.key]}
            warning={warningFor(def.key)}
            onChange={(v) => onField(def.key, v)}
          />
        ))}
      </div>
    </section>
  );
}
