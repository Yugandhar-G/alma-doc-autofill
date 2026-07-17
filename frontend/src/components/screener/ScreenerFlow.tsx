"use client";

import { useRef, useState } from "react";

import { ActivityFeed, appendFeedEvent } from "@/components/screener/ActivityFeed";
import { AgentRunStep } from "@/components/screener/AgentRunStep";
import { DisclaimerBanner } from "@/components/screener/DisclaimerBanner";
import {
  EvidenceUploadStep,
  type EvidenceSlotState,
} from "@/components/screener/EvidenceUploadStep";
import { IntakeStep } from "@/components/screener/IntakeStep";
import { MatrixReviewStep } from "@/components/screener/MatrixReviewStep";
import { ReportStep } from "@/components/screener/ReportStep";
import { StepIndicator } from "@/components/flow/StepIndicator";
import {
  createScreenerSession,
  streamReview,
  streamRun,
  submitIntake,
  uploadScreenerDocuments,
} from "@/lib/screener/api";
import {
  EMPTY_INTAKE,
  MAX_EVIDENCE_DOCS,
  answerIndex,
  type ActivityEvent,
  type EvidenceMatrix,
  type IntakeAnswers,
  type ScreenerEvent,
  type ScreenerReport,
  type VisaType,
} from "@/lib/screener/types";
import { validateFile } from "@/lib/fileValidation";
import { trackEvent } from "@/lib/telemetry";

/** compiling/assessing are the two SSE segments around the human-review gate. */
type StepId = "intake" | "uploads" | "compiling" | "matrix-review" | "assessing" | "report";

const STEPS = [
  { id: "intake", label: "Intake" },
  { id: "uploads", label: "Evidence" },
  { id: "matrix-review", label: "Review claims" },
  { id: "assessing", label: "Assessment" },
  { id: "report", label: "Report" },
] as const;

const STEP_INDEX: Record<StepId, number> = {
  intake: 0,
  uploads: 1,
  compiling: 2, // the agent is preparing the claims you are about to review
  "matrix-review": 2,
  assessing: 3,
  report: 4,
};

export function ScreenerFlow() {
  const [step, setStep] = useState<StepId>("intake");
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [intake, setIntake] = useState<IntakeAnswers>(EMPTY_INTAKE);
  const [visaTargets, setVisaTargets] = useState<VisaType[]>(["O1A", "EB1A"]);
  const [isSubmittingIntake, setIsSubmittingIntake] = useState(false);
  const [intakeError, setIntakeError] = useState<string | null>(null);

  const [resumeSlot, setResumeSlot] = useState<EvidenceSlotState | null>(null);
  const [evidenceSlots, setEvidenceSlots] = useState<EvidenceSlotState[]>([]);

  const [matrix, setMatrix] = useState<EvidenceMatrix | null>(null);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const [feed, setFeed] = useState<ActivityEvent[]>([]);
  const [finishedNodes, setFinishedNodes] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [report, setReport] = useState<ScreenerReport | null>(null);

  /** The matrix the user confirmed — what a retry of the review segment resends. */
  const confirmedMatrixRef = useRef<EvidenceMatrix | null>(null);

  function goTo(next: StepId) {
    trackEvent("ui.screener.step", { step: next });
    setStep(next);
  }

  // -- intake ---------------------------------------------------------------

  async function handleIntakeSubmit() {
    setIntakeError(null);
    setIsSubmittingIntake(true);
    try {
      let sid = sessionId;
      if (sid === null) {
        sid = await createScreenerSession();
        setSessionId(sid);
      }
      await submitIntake(sid, visaTargets, intake);
      trackEvent("ui.screener.intake", {
        visa_targets: visaTargets.join(","),
        answers: Object.keys(answerIndex(intake)).length,
      });
      goTo("uploads");
    } catch (err) {
      setIntakeError(err instanceof Error ? err.message : "Saving the intake failed unexpectedly.");
    } finally {
      setIsSubmittingIntake(false);
    }
  }

  // -- uploads --------------------------------------------------------------

  async function handleResumeSelect(file: File) {
    if (sessionId === null) return; // unreachable: uploads require a session
    const check = await validateFile(file, ["jpeg", "png", "pdf"]);
    if (!check.ok) {
      setResumeSlot({ file, isUploading: false, error: check.error, record: null });
      return;
    }
    setResumeSlot({ file, isUploading: true, error: null, record: null });
    try {
      const result = await uploadScreenerDocuments(sessionId, { resume: file });
      const slot = result.resume;
      if (slot === null) {
        setResumeSlot({
          file,
          isUploading: false,
          error: "The backend response was missing the resume result.",
          record: null,
        });
        return;
      }
      setResumeSlot({
        file,
        isUploading: false,
        error: slot.kind === "rejected" ? slot.error : null,
        record: slot.kind === "ok" ? slot.record : null,
      });
      trackEvent("ui.screener.upload", { slot: "resume", outcome: slot.kind });
    } catch (err) {
      setResumeSlot({
        file,
        isUploading: false,
        error: err instanceof Error ? err.message : "The upload failed unexpectedly.",
        record: null,
      });
    }
  }

  async function handleEvidenceAdd(files: File[]) {
    if (sessionId === null) return;
    const remaining = MAX_EVIDENCE_DOCS - evidenceSlots.length;
    const accepted = files.slice(0, remaining);

    const checks = await Promise.all(accepted.map((f) => validateFile(f, ["jpeg", "png", "pdf"])));
    const newSlots: EvidenceSlotState[] = accepted.map((file, i) => {
      const check = checks[i];
      return check.ok
        ? { file, isUploading: true, error: null, record: null }
        : { file, isUploading: false, error: check.error, record: null };
    });
    const baseIndex = evidenceSlots.length;
    setEvidenceSlots((prev) => [...prev, ...newSlots]);

    const toUpload = newSlots
      .map((slot, i) => ({ slot, index: baseIndex + i }))
      .filter(({ slot }) => slot.isUploading);
    if (toUpload.length === 0) return;

    try {
      const result = await uploadScreenerDocuments(sessionId, {
        evidence: toUpload.map(({ slot }) => slot.file),
      });
      setEvidenceSlots((prev) =>
        prev.map((slot, i) => {
          const position = toUpload.findIndex(({ index }) => index === i);
          if (position === -1) return slot;
          const outcome = result.evidence[position];
          if (outcome === undefined) {
            return {
              ...slot,
              isUploading: false,
              error: "The backend response was missing this slot's result.",
            };
          }
          return {
            ...slot,
            isUploading: false,
            error: outcome.kind === "rejected" ? outcome.error : null,
            record: outcome.kind === "ok" ? outcome.record : null,
          };
        }),
      );
      trackEvent("ui.screener.upload", {
        slot: "evidence",
        count: toUpload.length,
        rejected: result.evidence.filter((s) => s.kind === "rejected").length,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "The upload failed unexpectedly.";
      setEvidenceSlots((prev) =>
        prev.map((slot, i) =>
          toUpload.some(({ index }) => index === i)
            ? { ...slot, isUploading: false, error: message }
            : slot,
        ),
      );
    }
  }

  function handleEvidenceRemove(index: number) {
    setEvidenceSlots((prev) => prev.filter((_, i) => i !== index));
  }

  // -- streaming ------------------------------------------------------------

  function handleStreamEvent(event: ScreenerEvent) {
    switch (event.event) {
      case "run_started":
        setIsStreaming(true);
        break;
      case "node_finished":
        setFinishedNodes((prev) => (prev.includes(event.node) ? prev : [...prev, event.node]));
        break;
      case "activity":
        setFeed((prev) => appendFeedEvent(prev, event));
        break;
      case "awaiting_review":
        setMatrix(event.matrix ?? { items: [], unmapped_docs: [] });
        goTo("matrix-review");
        break;
      case "done":
        setReport(event.report);
        goTo("report");
        trackEvent("ui.screener.done", {
          verdicts: event.report.verdicts.length,
          warnings: event.report.warnings.length,
        });
        break;
      case "error":
        setRunError(event.message);
        break;
    }
  }

  async function startRun() {
    if (sessionId === null) return;
    setRunError(null);
    setReviewError(null);
    setFeed([]);
    setFinishedNodes([]);
    setIsStreaming(true);
    goTo("compiling");
    try {
      await streamRun(sessionId, handleStreamEvent);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "The screening run failed unexpectedly.");
    } finally {
      setIsStreaming(false);
    }
  }

  async function submitReview(confirmed: EvidenceMatrix) {
    if (sessionId === null) return;
    confirmedMatrixRef.current = confirmed;
    setReviewError(null);
    setRunError(null);
    setIsSubmittingReview(true);
    let streamOpened = false;
    try {
      await streamReview(sessionId, confirmed, (event) => {
        if (!streamOpened) {
          // First event: the resume was accepted — hand off to the run view.
          streamOpened = true;
          setIsSubmittingReview(false);
          goTo("assessing");
        }
        handleStreamEvent(event);
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Resuming the run failed unexpectedly.";
      // Setup rejections surface on the review table; mid-stream drops on the
      // run view. A retry from the run view can also fail during setup, so
      // both surfaces get the message — whichever is mounted shows it.
      setRunError(message);
      if (!streamOpened) setReviewError(message);
    } finally {
      setIsSubmittingReview(false);
      setIsStreaming(false);
    }
  }

  function retryFailedSegment() {
    if (step === "assessing" && confirmedMatrixRef.current !== null) {
      void submitReview(confirmedMatrixRef.current);
      goTo("assessing");
    } else {
      void startRun();
    }
  }

  function restart() {
    trackEvent("ui.screener.restart");
    setStep("intake");
    setSessionId(null);
    setIntake(EMPTY_INTAKE);
    setVisaTargets(["O1A", "EB1A"]);
    setIntakeError(null);
    setResumeSlot(null);
    setEvidenceSlots([]);
    setMatrix(null);
    setReviewError(null);
    setFeed([]);
    setFinishedNodes([]);
    setRunError(null);
    setReport(null);
    confirmedMatrixRef.current = null;
  }

  return (
    <div className="flex flex-col gap-6">
      <StepIndicator steps={STEPS} currentIndex={STEP_INDEX[step]} />
      <DisclaimerBanner text={report?.disclaimer} />

      {step === "intake" && (
        <IntakeStep
          intake={intake}
          visaTargets={visaTargets}
          isSubmitting={isSubmittingIntake}
          error={intakeError}
          onIntakeChange={setIntake}
          onVisaTargetsChange={setVisaTargets}
          onSubmit={handleIntakeSubmit}
        />
      )}

      {step === "uploads" && (
        <EvidenceUploadStep
          resume={resumeSlot}
          evidence={evidenceSlots}
          onResumeSelect={handleResumeSelect}
          onEvidenceAdd={handleEvidenceAdd}
          onEvidenceRemove={handleEvidenceRemove}
          onBack={() => goTo("intake")}
          onContinue={() => void startRun()}
        />
      )}

      {(step === "compiling" || step === "assessing") && (
        <AgentRunStep
          phase={step}
          finishedNodes={finishedNodes}
          feed={feed}
          isLive={isStreaming}
          error={runError}
          onRetry={retryFailedSegment}
        />
      )}

      {step === "matrix-review" && matrix && (
        <>
          <MatrixReviewStep
            matrix={matrix}
            answerIds={answerIndex(intake)}
            isSubmitting={isSubmittingReview}
            error={reviewError}
            onChange={setMatrix}
            onConfirm={() => void submitReview(matrix)}
          />
          <details className="group">
            <summary className="cursor-pointer text-xs font-medium text-ink-soft transition-colors hover:text-accent-deep">
              What the agent did to get here
            </summary>
            <div className="mt-3">
              <ActivityFeed feed={feed} isLive={false} />
            </div>
          </details>
        </>
      )}

      {step === "report" && report && <ReportStep report={report} onRestart={restart} />}
    </div>
  );
}
