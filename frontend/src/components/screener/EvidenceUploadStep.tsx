"use client";

import { useRef, useState, type DragEvent } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { FILE_ACCEPT, MAX_FILE_MB } from "@/lib/config";
import { MAX_EVIDENCE_DOCS, type EvidenceDocRecord, type EvidenceKind } from "@/lib/screener/types";

/** Upload + extraction state for one evidence slot, owned by ScreenerFlow. */
export type EvidenceSlotState = {
  file: File;
  isUploading: boolean;
  /** Guardrail or extraction rejection — pinned to this slot only. */
  error: string | null;
  record: EvidenceDocRecord | null;
};

const KIND_LABELS: Record<EvidenceKind, string> = {
  resume: "Resume",
  award: "Award",
  press: "Press",
  recommendation_letter: "Recommendation",
  publication: "Publication",
  salary_doc: "Salary doc",
  membership_proof: "Membership",
  patent: "Patent",
  other: "Other",
};

function KindBadge({ kind }: { kind: EvidenceKind }) {
  return (
    <span className="rounded-full border border-accent/30 bg-accent-wash px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-accent-deep">
      {KIND_LABELS[kind]}
    </span>
  );
}

function SlotRow({
  slot,
  onRemove,
}: {
  slot: EvidenceSlotState;
  onRemove: (() => void) | null;
}) {
  return (
    <li className="flex items-start gap-3 rounded-lg border border-line bg-paper/60 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {slot.record && <KindBadge kind={slot.record.document_kind_detected} />}
          <p className="truncate text-sm font-medium" title={slot.file.name}>
            {slot.record?.title ?? slot.file.name}
          </p>
        </div>
        {slot.isUploading && (
          <p className="mt-1 flex items-center gap-2 text-xs text-ink-soft" role="status">
            <span
              aria-hidden
              className="size-3 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent"
            />
            Validating and reading — this can take 10–30 seconds.
          </p>
        )}
        {slot.record && (
          <p className="mt-0.5 text-xs text-ink-faint">
            {slot.record.key_facts.length} key fact
            {slot.record.key_facts.length === 1 ? "" : "s"} extracted · included in the run
          </p>
        )}
        {slot.record && slot.record.warnings.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-xs text-warn">
            {slot.record.warnings.map((w) => (
              <li key={`${w.field}-${w.message}`}>{w.message}</li>
            ))}
          </ul>
        )}
        {slot.error && (
          <p role="alert" className="mt-1 text-xs font-medium text-danger">
            {slot.error}
          </p>
        )}
      </div>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="shrink-0 rounded px-2 py-1 text-xs font-medium text-ink-soft transition-colors hover:bg-line/50 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
        >
          Remove
        </button>
      )}
    </li>
  );
}

function DropZone({
  label,
  sublabel,
  isDisabled,
  multiple,
  onFiles,
}: {
  label: string;
  sublabel: string;
  isDisabled: boolean;
  multiple: boolean;
  onFiles: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (isDisabled) return;
    const dropped = Array.from(e.dataTransfer.files ?? []);
    if (dropped.length > 0) onFiles(multiple ? dropped : dropped.slice(0, 1));
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={FILE_ACCEPT}
        multiple={multiple}
        className="hidden"
        disabled={isDisabled}
        onChange={(e) => {
          const chosen = Array.from(e.target.files ?? []);
          if (chosen.length > 0) onFiles(chosen);
          e.target.value = ""; // allow re-selecting the same file after a fix
        }}
      />
      <button
        type="button"
        disabled={isDisabled}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          if (!isDisabled) setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={`flex w-full flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-6 py-6 text-center transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          isDragOver
            ? "border-accent bg-accent-wash"
            : "border-line-strong hover:border-accent/60 hover:bg-accent-wash/40"
        } ${isDisabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
      >
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-ink-faint">{sublabel}</span>
      </button>
    </>
  );
}

type Props = {
  resume: EvidenceSlotState | null;
  evidence: EvidenceSlotState[];
  onResumeSelect: (file: File) => void;
  onEvidenceAdd: (files: File[]) => void;
  onEvidenceRemove: (index: number) => void;
  onBack: () => void;
  onContinue: () => void;
};

export function EvidenceUploadStep({
  resume,
  evidence,
  onResumeSelect,
  onEvidenceAdd,
  onEvidenceRemove,
  onBack,
  onContinue,
}: Props) {
  const isBusy = resume?.isUploading === true || evidence.some((s) => s.isUploading);
  const acceptedCount =
    (resume?.record ? 1 : 0) + evidence.filter((s) => s.record !== null).length;
  const remaining = MAX_EVIDENCE_DOCS - evidence.length;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Add supporting documents.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Each document is read immediately — only verbatim excerpts from what it actually says can
          be cited later. This step is optional: an intake-only run is perfectly valid.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flex flex-col rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
          <div className="flex items-baseline gap-3 border-b border-line px-5 py-3.5">
            <span className="font-mono text-xs text-ink-faint">01</span>
            <h3 className="font-display text-lg">Resume</h3>
            <span className="ml-auto rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-soft">
              Optional
            </span>
          </div>
          <div className="flex flex-1 flex-col gap-3 p-5">
            {resume ? (
              <ul className="flex flex-col gap-2">
                <SlotRow slot={resume} onRemove={null} />
              </ul>
            ) : null}
            <DropZone
              label={resume ? "Replace the resume" : "Drop the resume here or click to browse"}
              sublabel={`PDF, JPG, or PNG · up to ${MAX_FILE_MB} MB`}
              isDisabled={isBusy}
              multiple={false}
              onFiles={(files) => onResumeSelect(files[0])}
            />
            <p className="text-xs leading-relaxed text-ink-faint">
              The backbone document — career history, roles, and publications feed most criteria.
              Re-uploading replaces the earlier resume.
            </p>
          </div>
        </div>

        <div className="flex flex-col rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
          <div className="flex items-baseline gap-3 border-b border-line px-5 py-3.5">
            <span className="font-mono text-xs text-ink-faint">02</span>
            <h3 className="font-display text-lg">Evidence</h3>
            <span className="ml-auto rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-soft">
              Up to {MAX_EVIDENCE_DOCS}
            </span>
          </div>
          <div className="flex flex-1 flex-col gap-3 p-5">
            {evidence.length > 0 && (
              <ul className="flex flex-col gap-2">
                {evidence.map((slot, i) => (
                  <SlotRow
                    key={`${slot.file.name}-${slot.file.size}-${i}`}
                    slot={slot}
                    // Accepted docs are buffered on the backend for the run and
                    // cannot be withdrawn from here — only failed slots clear.
                    onRemove={slot.record === null && !slot.isUploading ? () => onEvidenceRemove(i) : null}
                  />
                ))}
              </ul>
            )}
            {remaining > 0 ? (
              <DropZone
                label="Drop evidence files here or click to browse"
                sublabel={`Award letters, press, publications… · ${remaining} slot${remaining === 1 ? "" : "s"} left`}
                isDisabled={isBusy}
                multiple
                onFiles={onEvidenceAdd}
              />
            ) : (
              <Banner tone="info">
                All {MAX_EVIDENCE_DOCS} evidence slots are used.
              </Banner>
            )}
            <p className="text-xs leading-relaxed text-ink-faint">
              Each file is classified and reduced to verbatim key facts. A rejected file never
              affects the others.
            </p>
          </div>
        </div>
      </div>

      {acceptedCount === 0 && !isBusy && (
        <Banner tone="info">
          No documents yet — the screening will run on intake answers alone. Documents give the
          agent verbatim excerpts to cite, which materially strengthens verdicts.
        </Banner>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onBack} disabled={isBusy}>
          Back to intake
        </Button>
        <Button onClick={onContinue} disabled={isBusy}>
          {acceptedCount > 0
            ? `Start the screening with ${acceptedCount} document${acceptedCount === 1 ? "" : "s"}`
            : "Start the screening without documents"}
        </Button>
      </footer>
    </section>
  );
}
