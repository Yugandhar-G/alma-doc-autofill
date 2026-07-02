"use client";

import { useState } from "react";

import { UploadSlot } from "@/components/upload/UploadSlot";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { extractDocuments } from "@/lib/api";
import { validateFile, type FileKind } from "@/lib/fileValidation";
import type { ExtractionResult } from "@/lib/types";

type SlotState = {
  file: File | null;
  kind: FileKind | null;
  error: string | null;
};

const EMPTY_SLOT: SlotState = { file: null, kind: null, error: null };

type Props = {
  onComplete: (result: ExtractionResult) => void;
};

export function UploadStage({ onComplete }: Props) {
  const [passportSlot, setPassportSlot] = useState<SlotState>(EMPTY_SLOT);
  const [g28Slot, setG28Slot] = useState<SlotState>(EMPTY_SLOT);
  const [isExtracting, setIsExtracting] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const setters = { passport: setPassportSlot, g28: setG28Slot } as const;

  async function handleSelect(slot: "passport" | "g28", file: File) {
    const setSlot = setters[slot];
    const check = await validateFile(file, ["jpeg", "png", "pdf"]);
    if (!check.ok) {
      setSlot({ file: null, kind: null, error: check.error });
      return;
    }
    setSlot({ file, kind: check.kind, error: null });
    setGlobalError(null);
  }

  async function handleExtract() {
    setGlobalError(null);
    setIsExtracting(true);
    try {
      const result = await extractDocuments({
        passport: passportSlot.file,
        g28: g28Slot.file,
      });
      const passportRejection =
        result.passport?.kind === "rejected" ? result.passport.error : null;
      const g28Rejection = result.g28?.kind === "rejected" ? result.g28.error : null;

      if (passportRejection || g28Rejection) {
        // A guardrail turned a file away — surface it on its slot and stay here.
        if (passportRejection) {
          setPassportSlot((s) => ({ ...s, error: passportRejection }));
        }
        if (g28Rejection) {
          setG28Slot((s) => ({ ...s, error: g28Rejection }));
        }
        setGlobalError(
          "One of the documents was rejected before extraction. Fix or replace it and extract again.",
        );
        return;
      }
      onComplete(result);
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : "Extraction failed unexpectedly.");
    } finally {
      setIsExtracting(false);
    }
  }

  const hasAnyFile = passportSlot.file !== null || g28Slot.file !== null;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Start with the documents.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Upload the client&rsquo;s passport and the completed Form G-28. Each document is
          validated, read by the extraction model, and laid out for your review before anything
          touches the form. Fields that cannot be read stay blank — nothing is ever guessed.
        </p>
      </header>

      {globalError && <Banner tone="danger">{globalError}</Banner>}

      <div className="grid gap-5 sm:grid-cols-2">
        <UploadSlot
          slotNumber="01"
          title="Passport"
          description="The photo (data) page. Feeds the client identity fields in Part 3 of the form."
          file={passportSlot.file}
          kind={passportSlot.kind}
          error={passportSlot.error}
          isDisabled={isExtracting}
          onSelect={(f) => handleSelect("passport", f)}
          onClear={() => setPassportSlot(EMPTY_SLOT)}
        />
        <UploadSlot
          slotNumber="02"
          title="Form G-28"
          description="Notice of Entry of Appearance as Attorney. Feeds Parts 1–3: representative, eligibility, and client."
          file={g28Slot.file}
          kind={g28Slot.kind}
          error={g28Slot.error}
          isDisabled={isExtracting}
          onSelect={(f) => handleSelect("g28", f)}
          onClear={() => setG28Slot(EMPTY_SLOT)}
        />
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <p className="text-xs text-ink-faint">
          {isExtracting
            ? "Reading the documents — this can take 10–30 seconds."
            : "You can proceed with one document; the other's fields are simply skipped."}
        </p>
        <Button onClick={handleExtract} disabled={!hasAnyFile} isBusy={isExtracting}>
          {isExtracting ? "Extracting…" : "Extract"}
        </Button>
      </footer>
    </section>
  );
}
