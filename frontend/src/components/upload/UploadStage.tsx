"use client";

import { useState } from "react";

import { UploadSlot } from "@/components/upload/UploadSlot";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { extractDocuments } from "@/lib/api";
import { PASSPORT_LOW_FIELD_THRESHOLD } from "@/lib/config";
import { PASSPORT_FIELDS } from "@/lib/fields";
import { validateFile, type FileKind } from "@/lib/fileValidation";
import { backWarning, describeDetectedType } from "@/lib/review";
import { countFilled, type ExtractionResult } from "@/lib/types";

type SlotState = {
  file: File | null;
  kind: FileKind | null;
  error: string | null;
};

const EMPTY_SLOT: SlotState = { file: null, kind: null, error: null };

type SlotId = "front" | "back" | "g28";

type Props = {
  onComplete: (result: ExtractionResult) => void;
};

export function UploadStage({ onComplete }: Props) {
  const [frontSlot, setFrontSlot] = useState<SlotState>(EMPTY_SLOT);
  const [backSlot, setBackSlot] = useState<SlotState>(EMPTY_SLOT);
  const [g28Slot, setG28Slot] = useState<SlotState>(EMPTY_SLOT);
  const [isExtracting, setIsExtracting] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  /** Extraction succeeded but something deserves a look before review. */
  const [heldResult, setHeldResult] = useState<ExtractionResult | null>(null);

  const setters: Record<SlotId, (next: SlotState) => void> = {
    front: setFrontSlot,
    back: setBackSlot,
    g28: setG28Slot,
  };

  async function handleSelect(slot: SlotId, file: File) {
    const setSlot = setters[slot];
    const check = await validateFile(file, ["jpeg", "png", "pdf"]);
    if (!check.ok) {
      setSlot({ file: null, kind: null, error: check.error });
      return;
    }
    setSlot({ file, kind: check.kind, error: null });
    setGlobalError(null);
    setHeldResult(null); // results are stale once any file changes
  }

  function handleClear(slot: SlotId) {
    setters[slot](EMPTY_SLOT);
    setGlobalError(null);
    setHeldResult(null);
  }

  async function handleExtract() {
    setGlobalError(null);
    setHeldResult(null);
    if (backSlot.file && !frontSlot.file) {
      setFrontSlot((s) => ({
        ...s,
        error:
          "Add the front (photo) page — the back side cannot be extracted on its own. Or remove the back to continue without a passport.",
      }));
      return;
    }
    setIsExtracting(true);
    try {
      const result = await extractDocuments({
        passportFront: frontSlot.file,
        passportBack: backSlot.file,
        g28: g28Slot.file,
      });

      let hasBlockingIssue = false;
      if (result.passport?.kind === "rejected") {
        const frontError = result.passport.error;
        setFrontSlot((s) => ({
          ...s,
          error: `${frontError} Re-upload the passport photo page.`,
        }));
        hasBlockingIssue = true;
      }
      const passportEnvelope = result.passport?.kind === "ok" ? result.passport.envelope : null;
      if (passportEnvelope && passportEnvelope.document_type_detected !== "passport") {
        const detected = describeDetectedType(passportEnvelope.document_type_detected);
        setFrontSlot((s) => ({
          ...s,
          error: `This file was detected as ${detected}, not a passport — its data cannot be used. Re-upload the passport photo (data) page.`,
        }));
        hasBlockingIssue = true;
      }
      if (result.g28?.kind === "rejected") {
        const g28Error = result.g28.error;
        setG28Slot((s) => ({ ...s, error: g28Error }));
        hasBlockingIssue = true;
      }
      if (hasBlockingIssue) {
        setGlobalError(
          "A document was rejected before its data could be used. Fix or replace the flagged files and extract again.",
        );
        return;
      }

      const needsAttention =
        result.passportBackError !== null ||
        backWarning(passportEnvelope, "document_type_detected") !== undefined ||
        (passportEnvelope !== null &&
          countFilled(passportEnvelope.data ?? {}) <= PASSPORT_LOW_FIELD_THRESHOLD);

      if (needsAttention) {
        setHeldResult(result);
        return;
      }
      onComplete(result);
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : "Extraction failed unexpectedly.");
    } finally {
      setIsExtracting(false);
    }
  }

  // Derived attention state for the held (successful but flagged) extraction.
  const heldEnvelope = heldResult?.passport?.kind === "ok" ? heldResult.passport.envelope : null;
  const backRejection = heldResult?.passportBackError ?? null;
  const backDocTypeNotice = backWarning(heldEnvelope, "document_type_detected") ?? null;
  const backMergeNote = backWarning(heldEnvelope, "merge") ?? null;
  const readableCount = heldEnvelope ? countFilled(heldEnvelope.data ?? {}) : null;
  const isLowFieldPassport =
    readableCount !== null && readableCount <= PASSPORT_LOW_FIELD_THRESHOLD;

  const hasExtractable = frontSlot.file !== null || g28Slot.file !== null;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Start with the documents.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Upload both sides of the client&rsquo;s passport and the completed Form G-28. Each file
          is validated, read by the extraction model, and laid out for your review before anything
          touches the form. Fields that cannot be read stay blank — nothing is ever guessed.
        </p>
      </header>

      {globalError && <Banner tone="danger">{globalError}</Banner>}

      {heldResult && (
        <Banner tone="warn">
          <strong className="font-semibold">Check the flagged documents before continuing.</strong>
          <ul className="mt-1 list-inside list-disc space-y-1">
            {backRejection && (
              <li>
                The back side was rejected: {backRejection} Re-upload it, or continue without the
                back — the front&rsquo;s data stands on its own.
              </li>
            )}
            {backDocTypeNotice && (
              <li>
                {backDocTypeNotice} Its data was ignored — re-upload the back if you expected
                values from it, or continue with the front alone.
              </li>
            )}
            {isLowFieldPassport && (
              <li>
                Only {readableCount} of {PASSPORT_FIELDS.length} passport fields could be read —
                the image may be unclear. Re-upload a sharper front page, or continue and complete
                the values by hand in review.
              </li>
            )}
          </ul>
        </Banner>
      )}

      <div className="grid gap-6 lg:grid-cols-[5fr_3fr]">
        <section aria-label="Client passport">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
              Client passport
            </h3>
            <span className="text-xs text-ink-faint">
              Front is the data source · back fills gaps
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <UploadSlot
              slotNumber="01"
              title="Front — photo page"
              badge="Required"
              description="The machine-readable data page. Feeds the client identity fields in Part 3 of the form."
              file={frontSlot.file}
              kind={frontSlot.kind}
              error={frontSlot.error}
              notice={heldResult && isLowFieldPassport ? "Extraction was thin — a sharper image will read more fields." : null}
              isDisabled={isExtracting}
              onSelect={(f) => handleSelect("front", f)}
              onClear={() => handleClear("front")}
            />
            <UploadSlot
              slotNumber="02"
              title="Back"
              badge="Recommended"
              description="Some passports carry extra data on the back. Anything found only fills fields the front left blank."
              file={backSlot.file}
              kind={backSlot.kind}
              error={backSlot.error ?? backRejection}
              notice={backDocTypeNotice}
              infoNote={backMergeNote}
              isDisabled={isExtracting}
              onSelect={(f) => handleSelect("back", f)}
              onClear={() => handleClear("back")}
            />
          </div>
        </section>

        <section aria-label="Representative form" className="flex flex-col">
          <div className="mb-3 flex items-baseline justify-between">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
              Representative form
            </h3>
            <span className="text-xs text-ink-faint">Single upload</span>
          </div>
          <UploadSlot
            slotNumber="03"
            title="Form G-28"
            description="Notice of Entry of Appearance as Attorney. Feeds Parts 1–3: representative, eligibility, and client."
            file={g28Slot.file}
            kind={g28Slot.kind}
            error={g28Slot.error}
            isDisabled={isExtracting}
            onSelect={(f) => handleSelect("g28", f)}
            onClear={() => handleClear("g28")}
          />
        </section>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <p className="text-xs text-ink-faint">
          {isExtracting
            ? "Reading the documents — this can take 10–30 seconds."
            : heldResult
              ? "Re-upload a flagged file to extract again, or continue with what was read."
              : "You can proceed with the passport front alone or the G-28 alone; missing documents are simply skipped."}
        </p>
        {heldResult ? (
          <Button onClick={() => onComplete(heldResult)}>Continue to review</Button>
        ) : (
          <Button onClick={handleExtract} disabled={!hasExtractable} isBusy={isExtracting}>
            {isExtracting ? "Extracting…" : "Extract"}
          </Button>
        )}
      </footer>
    </section>
  );
}
