"use client";

import { useState } from "react";

import { DocumentStep, EMPTY_DOC, type DocState } from "@/components/flow/DocumentStep";
import { G28ReviewStep } from "@/components/flow/G28ReviewStep";
import { PassportReviewStep } from "@/components/flow/PassportReviewStep";
import { PopulateStep } from "@/components/flow/PopulateStep";
import { StepIndicator } from "@/components/flow/StepIndicator";
import { ReportStage } from "@/components/report/ReportStage";
import { extractDocuments, populateForm } from "@/lib/api";
import { PASSPORT_LOW_FIELD_THRESHOLD } from "@/lib/config";
import {
  ATTORNEY_FIELDS,
  BENEFICIARY_FIELDS,
  ELIGIBILITY_FIELDS,
  PASSPORT_FIELDS,
} from "@/lib/fields";
import { validateFile } from "@/lib/fileValidation";
import { trackEvent } from "@/lib/telemetry";
import {
  backWarning,
  describeDetectedType,
  fieldWarning,
  g28FromEnvelope,
  passportFromEnvelope,
  warningsByField,
} from "@/lib/review";
import {
  countFilled,
  type ExtractionEnvelope,
  type G28Data,
  type PassportData,
  type PopulationReport,
} from "@/lib/types";

type StepId = "front" | "back" | "passport-review" | "g28" | "g28-review" | "populate";

const STEPS: { id: StepId; label: string }[] = [
  { id: "front", label: "Passport · front" },
  { id: "back", label: "Passport · back" },
  { id: "passport-review", label: "Confirm passport" },
  { id: "g28", label: "Form G-28" },
  { id: "g28-review", label: "Confirm G-28" },
  { id: "populate", label: "Fill & report" },
];

const G28_FIELD_TOTAL =
  ATTORNEY_FIELDS.length + ELIGIBILITY_FIELDS.length + BENEFICIARY_FIELDS.length;

function g28FieldsRead(env: ExtractionEnvelope): number {
  const d = (env.data ?? {}) as Record<string, Record<string, unknown> | undefined>;
  return (
    countFilled(d.attorney ?? {}) +
    countFilled(d.eligibility ?? {}) +
    countFilled(d.beneficiary ?? {})
  );
}

export function AutofillFlow() {
  const [step, setStep] = useState<StepId>("front");
  const [front, setFront] = useState<DocState>(EMPTY_DOC);
  const [back, setBack] = useState<DocState>(EMPTY_DOC);
  const [g28Doc, setG28Doc] = useState<DocState>(EMPTY_DOC);
  // Editable review data — re-derived whenever a new extraction lands.
  const [passport, setPassport] = useState<PassportData | null>(null);
  const [g28, setG28] = useState<G28Data | null>(null);
  const [report, setReport] = useState<PopulationReport | null>(null);
  const [isPopulating, setIsPopulating] = useState(false);
  const [populateError, setPopulateError] = useState<string | null>(null);

  /** The authoritative passport envelope: merged (front+back) when the back ran, else front-only. */
  const passportEnvelope = back.envelope ?? front.envelope;

  function goTo(next: StepId) {
    trackEvent("ui.step", { step: next });
    setStep(next);
  }

  async function handleFrontSelect(file: File) {
    const check = await validateFile(file, ["jpeg", "png", "pdf"]);
    if (!check.ok) {
      setFront({ ...EMPTY_DOC, file, error: check.error });
      return;
    }
    setFront({ ...EMPTY_DOC, file, kind: check.kind, isExtracting: true });
    setBack(EMPTY_DOC); // a new front invalidates any earlier merge
    try {
      const result = await extractDocuments({ passportFront: file, passportBack: null, g28: null });
      if (result.passport?.kind !== "ok") {
        const message =
          result.passport?.kind === "rejected"
            ? result.passport.error
            : "The backend response was missing the passport result.";
        setFront({ ...EMPTY_DOC, file, kind: check.kind, error: message });
        return;
      }
      const envelope = result.passport.envelope;
      if (envelope.document_type_detected !== "passport") {
        setFront({
          ...EMPTY_DOC,
          file,
          kind: check.kind,
          error: `This file was detected as ${describeDetectedType(envelope.document_type_detected)}, not a passport. Upload the passport photo (data) page.`,
        });
        return;
      }
      const fieldsRead = countFilled(envelope.data ?? {});
      const notice =
        fieldsRead <= PASSPORT_LOW_FIELD_THRESHOLD
          ? `Only ${fieldsRead} of ${PASSPORT_FIELDS.length} fields could be read — a sharper image will read more. You can also continue and complete values by hand in review.`
          : null;
      setFront({ file, kind: check.kind, error: null, notice, infoNote: null, isExtracting: false, envelope });
      setPassport(passportFromEnvelope(envelope));
      trackEvent("ui.extract", { doc: "passport_front", outcome: "ok", fields_read: fieldsRead });
    } catch (err) {
      setFront({
        ...EMPTY_DOC,
        file,
        kind: check.kind,
        error: err instanceof Error ? err.message : "Extraction failed unexpectedly.",
      });
    }
  }

  async function handleBackSelect(file: File) {
    if (!front.file) return; // unreachable: the back step requires a front
    const check = await validateFile(file, ["jpeg", "png", "pdf"]);
    if (!check.ok) {
      setBack({ ...EMPTY_DOC, file, error: check.error });
      return;
    }
    setBack({ ...EMPTY_DOC, file, kind: check.kind, isExtracting: true });
    try {
      const result = await extractDocuments({
        passportFront: front.file,
        passportBack: file,
        g28: null,
      });
      if (result.passport?.kind !== "ok") {
        const message =
          result.passport?.kind === "rejected"
            ? result.passport.error
            : "The backend response was missing the passport result.";
        setBack({ ...EMPTY_DOC, file, kind: check.kind, error: message });
        return;
      }
      const envelope = result.passport.envelope;
      const backRejection = result.passportBackError;
      const backTypeNote = backWarning(envelope, "document_type_detected") ?? null;
      const notice = backRejection
        ? `${backRejection} You can re-upload it or continue — the front's data stands on its own.`
        : backTypeNote
          ? `${backTypeNote} Its data was ignored; the front's values are used.`
          : null;
      setBack({
        file,
        kind: check.kind,
        error: null,
        notice,
        infoNote: backWarning(envelope, "merge") ?? null,
        isExtracting: false,
        envelope,
      });
      setPassport(passportFromEnvelope(envelope));
      trackEvent("ui.extract", {
        doc: "passport_back",
        outcome: backRejection ? "rejected" : backTypeNote ? "ignored" : "ok",
        fields_read: countFilled(envelope.data ?? {}),
      });
    } catch (err) {
      setBack({
        ...EMPTY_DOC,
        file,
        kind: check.kind,
        error: err instanceof Error ? err.message : "Extraction failed unexpectedly.",
      });
    }
  }

  async function handleG28Select(file: File) {
    const check = await validateFile(file, ["jpeg", "png", "pdf"]);
    if (!check.ok) {
      setG28Doc({ ...EMPTY_DOC, file, error: check.error });
      return;
    }
    setG28Doc({ ...EMPTY_DOC, file, kind: check.kind, isExtracting: true });
    try {
      const result = await extractDocuments({ passportFront: null, passportBack: null, g28: file });
      if (result.g28?.kind !== "ok") {
        const message =
          result.g28?.kind === "rejected"
            ? result.g28.error
            : "The backend response was missing the G-28 result.";
        setG28Doc({ ...EMPTY_DOC, file, kind: check.kind, error: message });
        return;
      }
      const envelope = result.g28.envelope;
      if (envelope.document_type_detected !== "g28") {
        setG28Doc({
          ...EMPTY_DOC,
          file,
          kind: check.kind,
          error: `This file was detected as ${describeDetectedType(envelope.document_type_detected)}, not a Form G-28. Upload the completed G-28.`,
        });
        return;
      }
      setG28Doc({ file, kind: check.kind, error: null, notice: null, infoNote: null, isExtracting: false, envelope });
      setG28(g28FromEnvelope(envelope));
      trackEvent("ui.extract", { doc: "g28", outcome: "ok", fields_read: g28FieldsRead(envelope) });
    } catch (err) {
      setG28Doc({
        ...EMPTY_DOC,
        file,
        kind: check.kind,
        error: err instanceof Error ? err.message : "Extraction failed unexpectedly.",
      });
    }
  }

  async function handlePopulate() {
    setPopulateError(null);
    setIsPopulating(true);
    try {
      const nextReport = await populateForm(passport, g28);
      setReport(nextReport);
      trackEvent("ui.populate", {
        outcome: nextReport.ok ? "ok" : "issues",
        filled: nextReport.filled,
        mismatches: nextReport.mismatches,
        errors: nextReport.errors,
      });
    } catch (err) {
      setPopulateError(err instanceof Error ? err.message : "Form population failed unexpectedly.");
      trackEvent("ui.populate", { outcome: "error" });
    } finally {
      setIsPopulating(false);
    }
  }

  function restart() {
    trackEvent("ui.restart");
    setStep("front");
    setFront(EMPTY_DOC);
    setBack(EMPTY_DOC);
    setG28Doc(EMPTY_DOC);
    setPassport(null);
    setG28(null);
    setReport(null);
    setPopulateError(null);
  }

  const reviewBackTarget: StepId = g28 ? "g28-review" : passport ? "passport-review" : "g28";
  const passportWarnings = warningsByField(passportEnvelope);
  const currentIndex = STEPS.findIndex((s) => s.id === step);

  return (
    <div className="flex flex-col gap-8">
      <StepIndicator steps={STEPS} currentIndex={currentIndex} />

      {step === "front" && (
        <DocumentStep
          title="Start with the passport — front."
          description="Upload the photo (data) page of the client's passport. It is validated and read immediately; you will confirm every value before anything touches the form."
          slotNumber="01"
          slotTitle="Front — photo page"
          slotBadge="Required"
          slotDescription="The machine-readable data page. Feeds the client identity fields in Part 3 of the form."
          doc={front}
          summary={
            front.envelope
              ? {
                  detectedLabel: describeDetectedType(front.envelope.document_type_detected),
                  fieldsRead: countFilled(front.envelope.data ?? {}),
                  fieldsTotal: PASSPORT_FIELDS.length,
                  warnings: front.envelope.warnings.map((w) => w.message),
                }
              : null
          }
          canContinue={front.envelope !== null && front.error === null}
          continueLabel="Continue to the back side"
          onSelect={handleFrontSelect}
          onClear={() => {
            setFront(EMPTY_DOC);
            setBack(EMPTY_DOC);
            setPassport(null);
          }}
          onContinue={() => goTo("back")}
          skipLabel="Continue without a passport"
          onSkip={() => {
            setFront(EMPTY_DOC);
            setBack(EMPTY_DOC);
            setPassport(null);
            trackEvent("ui.skip", { doc: "passport" });
            goTo("g28");
          }}
        />
      )}

      {step === "back" && (
        <DocumentStep
          title="Now the back side."
          description="Most passport backs carry little or no data — anything found only fills fields the front left blank. If there is nothing useful on the back, continue without it."
          slotNumber="02"
          slotTitle="Back"
          slotBadge="Optional"
          slotDescription="Some passports carry extra data on the back. The front side stays authoritative."
          doc={back}
          summary={
            back.envelope
              ? {
                  detectedLabel:
                    backWarning(back.envelope, "document_type_detected") || back.notice
                      ? "not a passport data page (ignored)"
                      : "a passport",
                  fieldsRead: countFilled(back.envelope.data ?? {}),
                  fieldsTotal: PASSPORT_FIELDS.length,
                  warnings: back.envelope.warnings
                    .filter((w) => w.field.startsWith("back:"))
                    .map((w) => w.message),
                }
              : null
          }
          canContinue={!back.isExtracting && back.error === null}
          continueLabel={back.envelope ? "Review the passport data" : "Continue without the back"}
          onSelect={handleBackSelect}
          onClear={() => setBack(EMPTY_DOC)}
          onContinue={() => goTo("passport-review")}
          onBack={() => goTo("front")}
        />
      )}

      {step === "passport-review" && passport && (
        <PassportReviewStep
          passport={passport}
          warningFor={(key) => fieldWarning(passportWarnings, key)}
          backMergeNote={backWarning(passportEnvelope, "merge") ?? null}
          onChange={setPassport}
          onBack={() => goTo("back")}
          onConfirm={() => goTo("g28")}
        />
      )}

      {step === "g28" && (
        <DocumentStep
          title="Now the Form G-28."
          description="Upload the completed Notice of Entry of Appearance. Multi-page PDFs are read page by page; you confirm every value on the next step."
          slotNumber="03"
          slotTitle="Form G-28"
          slotBadge="Required"
          slotDescription="Feeds Parts 1–3 of the target form: representative, eligibility, and client."
          doc={g28Doc}
          summary={
            g28Doc.envelope
              ? {
                  detectedLabel: describeDetectedType(g28Doc.envelope.document_type_detected),
                  fieldsRead: g28FieldsRead(g28Doc.envelope),
                  fieldsTotal: G28_FIELD_TOTAL,
                  warnings: g28Doc.envelope.warnings.map((w) => w.message),
                }
              : null
          }
          canContinue={g28Doc.envelope !== null && g28Doc.error === null}
          continueLabel="Review the G-28 data"
          onSelect={handleG28Select}
          onClear={() => {
            setG28Doc(EMPTY_DOC);
            setG28(null);
          }}
          onContinue={() => goTo("g28-review")}
          onBack={() => goTo(passport ? "passport-review" : "front")}
          skipLabel="Continue without the G-28"
          onSkip={() => {
            setG28Doc(EMPTY_DOC);
            setG28(null);
            trackEvent("ui.skip", { doc: "g28" });
            goTo("populate");
          }}
        />
      )}

      {step === "g28-review" && g28 && (
        <G28ReviewStep
          g28={g28}
          warnings={warningsByField(g28Doc.envelope)}
          onChange={setG28}
          onBack={() => goTo("g28")}
          onConfirm={() => goTo("populate")}
        />
      )}

      {step === "populate" &&
        (report ? (
          <ReportStage
            report={report}
            onBackToReview={() => {
              setReport(null);
              goTo(reviewBackTarget);
            }}
            onRestart={restart}
          />
        ) : (
          <PopulateStep
            passport={passport}
            g28={g28}
            isPopulating={isPopulating}
            error={populateError}
            onPopulate={handlePopulate}
            onBack={() => goTo(reviewBackTarget)}
          />
        ))}
    </div>
  );
}
