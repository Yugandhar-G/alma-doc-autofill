"use client";

import { UploadSlot } from "@/components/upload/UploadSlot";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import type { ExtractionEnvelope } from "@/lib/types";
import type { FileKind } from "@/lib/fileValidation";

/** Upload + extraction state for one document step, owned by AutofillFlow. */
export type DocState = {
  file: File | null;
  kind: FileKind | null;
  /** Hard failure — blocks Continue until the file is replaced. */
  error: string | null;
  /** Soft caution — shown amber, Continue stays available. */
  notice: string | null;
  infoNote: string | null;
  isExtracting: boolean;
  envelope: ExtractionEnvelope | null;
};

export const EMPTY_DOC: DocState = {
  file: null,
  kind: null,
  error: null,
  notice: null,
  infoNote: null,
  isExtracting: false,
  envelope: null,
};

type Summary = {
  /** Human phrasing of document_type_detected, e.g. "a passport". */
  detectedLabel: string;
  fieldsRead: number;
  fieldsTotal: number;
  warnings: string[];
};

type Props = {
  title: string;
  description: string;
  slotNumber: string;
  slotTitle: string;
  slotBadge?: string;
  slotDescription: string;
  doc: DocState;
  /** Extraction summary panel — null until a successful extraction. */
  summary: Summary | null;
  canContinue: boolean;
  continueLabel: string;
  onSelect: (file: File) => void;
  onClear: () => void;
  onContinue: () => void;
  onBack?: () => void;
  /** Optional escape hatch, e.g. "Continue without the back side". */
  skipLabel?: string;
  onSkip?: () => void;
};

export function DocumentStep({
  title,
  description,
  slotNumber,
  slotTitle,
  slotBadge,
  slotDescription,
  doc,
  summary,
  canContinue,
  continueLabel,
  onSelect,
  onClear,
  onContinue,
  onBack,
  skipLabel,
  onSkip,
}: Props) {
  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">{title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">{description}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[5fr_3fr]">
        <UploadSlot
          slotNumber={slotNumber}
          title={slotTitle}
          badge={slotBadge}
          description={slotDescription}
          file={doc.file}
          kind={doc.kind}
          error={doc.error}
          notice={doc.notice}
          infoNote={doc.infoNote}
          isDisabled={doc.isExtracting}
          onSelect={onSelect}
          onClear={onClear}
        />

        <aside aria-label="Extraction result" className="flex flex-col justify-start gap-3">
          {doc.isExtracting && (
            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-5">
              <span
                aria-hidden
                className="size-5 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent"
              />
              <p className="text-sm text-ink-soft" role="status">
                Validating and reading the document — this can take 10–30 seconds.
              </p>
            </div>
          )}

          {!doc.isExtracting && summary && (
            <div className="rounded-xl border border-line bg-surface p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
                Extraction result
              </p>
              <p className="mt-2 text-sm">
                Recognized as <strong className="font-semibold">{summary.detectedLabel}</strong>.
              </p>
              <p className="mt-1 font-display text-3xl">
                {summary.fieldsRead}
                <span className="text-base text-ink-faint"> of {summary.fieldsTotal} fields read</span>
              </p>
              {summary.warnings.length > 0 && (
                <ul className="mt-3 space-y-1 rounded-lg border border-warn/30 bg-warn-wash p-3 text-xs leading-relaxed text-warn">
                  {summary.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {!doc.isExtracting && !summary && !doc.error && (
            <Banner tone="info">
              The document is validated and read as soon as you drop it — you will see exactly what
              was recognized before moving on.
            </Banner>
          )}
        </aside>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <div>
          {onBack && (
            <Button variant="ghost" onClick={onBack} disabled={doc.isExtracting}>
              Back
            </Button>
          )}
        </div>
        <div className="flex items-center gap-3">
          {skipLabel && onSkip && (
            <Button variant="ghost" onClick={onSkip} disabled={doc.isExtracting}>
              {skipLabel}
            </Button>
          )}
          <Button onClick={onContinue} disabled={!canContinue || doc.isExtracting}>
            {continueLabel}
          </Button>
        </div>
      </footer>
    </section>
  );
}
