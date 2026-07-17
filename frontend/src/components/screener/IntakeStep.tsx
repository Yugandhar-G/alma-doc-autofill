"use client";

import type { ReactNode } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import {
  INTAKE_MAX_CHARS,
  INTAKE_MAX_LIST_ENTRIES,
  answerIndex,
  type IntakeAnswers,
  type VisaType,
} from "@/lib/screener/types";

type ScalarKey =
  | "field_of_endeavor"
  | "current_role"
  | "salary_context"
  | "judging_activity"
  | "publications_summary"
  | "original_contributions"
  | "critical_roles"
  | "exhibitions"
  | "commercial_success"
  | "one_time_major_award";

type ListKey = "awards" | "memberships" | "press_mentions";

type ScalarDef = { key: ScalarKey; label: string; hint: string };
type ListDef = { key: ListKey; label: string; hint: string; entryPlaceholder: string };

const ABOUT_FIELDS: ScalarDef[] = [
  {
    key: "field_of_endeavor",
    label: "Field of endeavor",
    hint: "The specific field the case is built around, e.g. distributed-systems research.",
  },
  {
    key: "current_role",
    label: "Current role",
    hint: "Role, employer, and what the person actually does.",
  },
  {
    key: "one_time_major_award",
    label: "One-time major award",
    hint: "A major internationally recognized award (Nobel-class), if any. Leave blank otherwise.",
  },
];

const CRITERIA_FIELDS: ScalarDef[] = [
  {
    key: "judging_activity",
    label: "Judging others' work",
    hint: "Peer review, program committees, competition judging.",
  },
  {
    key: "publications_summary",
    label: "Publications",
    hint: "Venues, counts, citation totals if known.",
  },
  {
    key: "original_contributions",
    label: "Original contributions",
    hint: "What the person built or discovered, and who adopted it.",
  },
  {
    key: "critical_roles",
    label: "Critical roles",
    hint: "Critical or essential roles at distinguished organizations.",
  },
  {
    key: "salary_context",
    label: "Compensation",
    hint: "Compensation and any comparator context (percentile, survey, geography).",
  },
  {
    key: "exhibitions",
    label: "Exhibitions (EB-1A)",
    hint: "Artistic exhibitions or showcases, if applicable.",
  },
  {
    key: "commercial_success",
    label: "Commercial success (EB-1A)",
    hint: "Box office, sales, streaming numbers — performing arts only.",
  },
];

const LIST_FIELDS: ListDef[] = [
  {
    key: "awards",
    label: "Awards",
    hint: "One award per entry, with year and scope.",
    entryPlaceholder: "e.g. ACM Distinguished Paper Award, 2023 (international)",
  },
  {
    key: "memberships",
    label: "Memberships",
    hint: "Associations that require outstanding achievement to join.",
    entryPlaceholder: "e.g. IEEE Senior Member, elected 2022",
  },
  {
    key: "press_mentions",
    label: "Press mentions",
    hint: "Outlet plus headline and date per entry.",
    entryPlaceholder: "e.g. TechCrunch — “…” (2024-03-01)",
  },
];

const TEXTAREA_CLASS =
  "w-full resize-y rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink " +
  "placeholder:italic placeholder:text-ink-faint focus:border-accent focus:outline-none " +
  "focus:ring-2 focus:ring-accent/20";

const COUNTER_SHOW_AT = Math.floor(INTAKE_MAX_CHARS * 0.85);

function CharCounter({ length }: { length: number }) {
  if (length < COUNTER_SHOW_AT) return null;
  const isOver = length > INTAKE_MAX_CHARS;
  return (
    <span className={`text-xs tabular-nums ${isOver ? "font-semibold text-danger" : "text-ink-faint"}`}>
      {length} / {INTAKE_MAX_CHARS}
    </span>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <header className="border-b border-line bg-paper/50 px-5 py-3.5">
        <h3 className="font-display text-lg">{title}</h3>
        <p className="text-xs text-ink-soft">{subtitle}</p>
      </header>
      <div className="flex flex-col gap-5 px-5 py-4">{children}</div>
    </section>
  );
}

function ScalarField({
  def,
  value,
  onChange,
}: {
  def: ScalarDef;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const text = value ?? "";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={`intake-${def.key}`} className="text-sm text-ink-soft">
          {def.label}
        </label>
        <CharCounter length={text.length} />
      </div>
      <p className="mb-1.5 text-xs text-ink-faint">{def.hint}</p>
      <textarea
        id={`intake-${def.key}`}
        rows={2}
        className={`${TEXTAREA_CLASS} ${text.length > INTAKE_MAX_CHARS ? "border-danger/50" : ""}`}
        placeholder="Leave blank if not applicable — unanswered is a valid answer"
        value={text}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      />
    </div>
  );
}

function ListField({
  def,
  entries,
  onChange,
}: {
  def: ListDef;
  entries: string[];
  onChange: (entries: string[]) => void;
}) {
  const canAdd = entries.length < INTAKE_MAX_LIST_ENTRIES;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-ink-soft">{def.label}</span>
        <span className="text-xs tabular-nums text-ink-faint">
          {entries.length} / {INTAKE_MAX_LIST_ENTRIES}
        </span>
      </div>
      <p className="mb-1.5 text-xs text-ink-faint">{def.hint}</p>
      <div className="flex flex-col gap-2">
        {entries.map((entry, i) => (
          <div key={i} className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <textarea
                rows={1}
                aria-label={`${def.label} entry ${i + 1}`}
                className={`${TEXTAREA_CLASS} ${entry.length > INTAKE_MAX_CHARS ? "border-danger/50" : ""}`}
                placeholder={def.entryPlaceholder}
                value={entry}
                onChange={(e) =>
                  onChange(entries.map((v, j) => (j === i ? e.target.value : v)))
                }
              />
              <div className="flex justify-end">
                <CharCounter length={entry.length} />
              </div>
            </div>
            <button
              type="button"
              aria-label={`Remove ${def.label} entry ${i + 1}`}
              onClick={() => onChange(entries.filter((_, j) => j !== i))}
              className="mt-1 rounded px-2 py-1 text-xs font-medium text-ink-soft transition-colors hover:bg-line/50 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          disabled={!canAdd}
          onClick={() => onChange([...entries, ""])}
          className="self-start rounded px-2 py-1 text-xs font-medium text-accent-deep transition-colors hover:bg-accent-wash focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          + Add {entries.length === 0 ? `a ${def.label.toLowerCase().replace(/s$/, "")}` : "another"}
        </button>
      </div>
    </div>
  );
}

const VISA_OPTIONS: { value: VisaType; label: string; note: string }[] = [
  { value: "O1A", label: "O-1A", note: "Extraordinary ability — nonimmigrant" },
  { value: "EB1A", label: "EB-1A", note: "Extraordinary ability — immigrant petition" },
];

type Props = {
  intake: IntakeAnswers;
  visaTargets: VisaType[];
  isSubmitting: boolean;
  error: string | null;
  onIntakeChange: (next: IntakeAnswers) => void;
  onVisaTargetsChange: (next: VisaType[]) => void;
  onSubmit: () => void;
};

export function IntakeStep({
  intake,
  visaTargets,
  isSubmitting,
  error,
  onIntakeChange,
  onVisaTargetsChange,
  onSubmit,
}: Props) {
  const setScalar = (key: ScalarKey, value: string | null) =>
    onIntakeChange({ ...intake, [key]: value });
  const setList = (key: ListKey, entries: string[]) =>
    onIntakeChange({ ...intake, [key]: entries });

  const toggleVisa = (visa: VisaType) => {
    const next = visaTargets.includes(visa)
      ? visaTargets.filter((v) => v !== visa)
      : [...visaTargets, visa];
    onVisaTargetsChange(next);
  };

  const overLimit =
    [...ABOUT_FIELDS, ...CRITERIA_FIELDS].some(
      (def) => (intake[def.key] ?? "").length > INTAKE_MAX_CHARS,
    ) ||
    LIST_FIELDS.some((def) =>
      intake[def.key].some((entry) => entry.length > INTAKE_MAX_CHARS),
    );
  const answerCount = Object.keys(answerIndex(intake)).length;
  const canSubmit = visaTargets.length > 0 && !overLimit;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Tell us about the case.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Answer what you can — every answer becomes citable evidence with a stable id, and blank
          answers are simply not cited. Nothing here is ever guessed or embellished.
        </p>
      </header>

      <fieldset className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
        <legend className="px-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
          Visa targets
        </legend>
        <div className="flex flex-wrap gap-4">
          {VISA_OPTIONS.map((option) => (
            <label
              key={option.value}
              className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-2.5 transition-colors duration-150 ${
                visaTargets.includes(option.value)
                  ? "border-accent bg-accent-wash"
                  : "border-line hover:border-accent/60"
              }`}
            >
              <input
                type="checkbox"
                className="size-4 accent-[var(--color-accent)]"
                checked={visaTargets.includes(option.value)}
                onChange={() => toggleVisa(option.value)}
              />
              <span>
                <span className="block text-sm font-medium">{option.label}</span>
                <span className="block text-xs text-ink-faint">{option.note}</span>
              </span>
            </label>
          ))}
        </div>
        {visaTargets.length === 0 && (
          <p className="mt-2 text-xs font-medium text-danger" role="alert">
            Select at least one visa target.
          </p>
        )}
      </fieldset>

      <Section
        title="The person and their field"
        subtitle="Anchors every criterion assessment — who this is and what field they claim standing in."
      >
        {ABOUT_FIELDS.map((def) => (
          <ScalarField
            key={def.key}
            def={def}
            value={intake[def.key]}
            onChange={(v) => setScalar(def.key, v)}
          />
        ))}
      </Section>

      <Section
        title="Recognition"
        subtitle="Concrete, dateable entries work best — each one gets its own citation id."
      >
        {LIST_FIELDS.map((def) => (
          <ListField
            key={def.key}
            def={def}
            entries={intake[def.key]}
            onChange={(entries) => setList(def.key, entries)}
          />
        ))}
      </Section>

      <Section
        title="Criterion evidence"
        subtitle="Each answer maps to specific USCIS criteria. Skip anything that does not apply."
      >
        {CRITERIA_FIELDS.map((def) => (
          <ScalarField
            key={def.key}
            def={def}
            value={intake[def.key]}
            onChange={(v) => setScalar(def.key, v)}
          />
        ))}
      </Section>

      {answerCount === 0 && (
        <Banner tone="info">
          No answers yet. You can still continue and rely on uploaded documents, but a few concrete
          answers give the screener far more to verify against.
        </Banner>
      )}
      {overLimit && (
        <Banner tone="danger">
          One or more answers exceed the {INTAKE_MAX_CHARS}-character limit — trim them before
          continuing.
        </Banner>
      )}
      {error && <Banner tone="danger">{error}</Banner>}

      <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-5">
        <Button onClick={onSubmit} disabled={!canSubmit} isBusy={isSubmitting}>
          {isSubmitting ? "Saving intake…" : "Continue to evidence"}
        </Button>
      </footer>
    </section>
  );
}
