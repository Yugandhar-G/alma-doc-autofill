"use client";

import { useState } from "react";

import { ReportStage } from "@/components/report/ReportStage";
import { ReviewStage } from "@/components/review/ReviewStage";
import { UploadStage } from "@/components/upload/UploadStage";
import { StepIndicator } from "@/components/flow/StepIndicator";
import { populateForm } from "@/lib/api";
import { g28FromEnvelope, passportFromEnvelope } from "@/lib/review";
import type {
  ExtractionEnvelope,
  ExtractionResult,
  G28Data,
  PassportData,
  PopulationReport,
} from "@/lib/types";

type Stage = "upload" | "review" | "report";

const STEPS = [
  { id: "upload", label: "Upload" },
  { id: "review", label: "Review & edit" },
  { id: "report", label: "Population report" },
] as const;

const STAGE_INDEX: Record<Stage, number> = { upload: 0, review: 1, report: 2 };

function envelopeOf(result: ExtractionResult, slot: "passport" | "g28"): ExtractionEnvelope | null {
  const outcome = result[slot];
  return outcome?.kind === "ok" ? outcome.envelope : null;
}

export function AutofillFlow() {
  const [stage, setStage] = useState<Stage>("upload");
  const [passportEnvelope, setPassportEnvelope] = useState<ExtractionEnvelope | null>(null);
  const [g28Envelope, setG28Envelope] = useState<ExtractionEnvelope | null>(null);
  const [passport, setPassport] = useState<PassportData | null>(null);
  const [g28, setG28] = useState<G28Data | null>(null);
  const [report, setReport] = useState<PopulationReport | null>(null);
  const [isPopulating, setIsPopulating] = useState(false);
  const [populateError, setPopulateError] = useState<string | null>(null);

  function handleExtracted(result: ExtractionResult) {
    const pEnv = envelopeOf(result, "passport");
    const gEnv = envelopeOf(result, "g28");
    setPassportEnvelope(pEnv);
    setG28Envelope(gEnv);
    setPassport(pEnv ? passportFromEnvelope(pEnv) : null);
    setG28(gEnv ? g28FromEnvelope(gEnv) : null);
    setReport(null);
    setPopulateError(null);
    setStage("review");
  }

  async function handlePopulate() {
    setPopulateError(null);
    setIsPopulating(true);
    try {
      const nextReport = await populateForm(passport, g28);
      setReport(nextReport);
      setStage("report");
    } catch (err) {
      setPopulateError(
        err instanceof Error ? err.message : "Form population failed unexpectedly.",
      );
    } finally {
      setIsPopulating(false);
    }
  }

  function restart() {
    setStage("upload");
    setPassportEnvelope(null);
    setG28Envelope(null);
    setPassport(null);
    setG28(null);
    setReport(null);
    setPopulateError(null);
  }

  return (
    <div className="flex flex-col gap-8">
      <StepIndicator steps={STEPS} currentIndex={STAGE_INDEX[stage]} />

      {stage === "upload" && <UploadStage onComplete={handleExtracted} />}

      {stage === "review" && (
        <ReviewStage
          passportEnvelope={passportEnvelope}
          g28Envelope={g28Envelope}
          passport={passport}
          g28={g28}
          isPopulating={isPopulating}
          populateError={populateError}
          onPassportChange={setPassport}
          onG28Change={setG28}
          onPopulate={handlePopulate}
          onRestart={restart}
        />
      )}

      {stage === "report" && report && (
        <ReportStage
          report={report}
          onBackToReview={() => setStage("review")}
          onRestart={restart}
        />
      )}
    </div>
  );
}
