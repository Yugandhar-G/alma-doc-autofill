"use client";

import { useState } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Chip, severityTone } from "@/components/ui/Chip";
import type { PreflightFinding, PreflightReport } from "@/lib/matters/types";

/**
 * Interrupt panel for the preflight `preflight_review` kind. Renders the draft
 * findings as an approve/remove review table; on submit it sends the approved
 * subset back through the resume endpoint (which re-validates each finding
 * through the same PreflightFinding schema the battery emits).
 *
 * payload = { report: PreflightReport, ... }
 */
type Props = {
  payload: Record<string, unknown>;
  onSubmit: (findings: PreflightFinding[]) => void;
  isSubmitting?: boolean;
  submitError?: string | null;
};

function readReport(payload: Record<string, unknown>): PreflightReport | null {
  const report = payload.report;
  if (report === null || typeof report !== "object") return null;
  return report as PreflightReport;
}

export function PreflightReviewPanel({ payload, onSubmit, isSubmitting, submitError }: Props) {
  const report = readReport(payload);
  const findings = report?.findings ?? [];

  // All findings start approved; removing one drops it from the approved set.
  const [approved, setApproved] = useState<boolean[]>(() => findings.map(() => true));

  if (report === null) {
    return <Banner tone="danger">This review is missing its draft report.</Banner>;
  }

  const toggle = (index: number) => {
    setApproved((prev) => prev.map((value, i) => (i === index ? !value : value)));
  };

  const approvedFindings = findings.filter((_, i) => approved[i]);

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm leading-relaxed text-ink-soft">
        The deterministic battery ran {report.checks_run.length} check
        {report.checks_run.length === 1 ? "" : "s"} across {report.docs_examined} document
        {report.docs_examined === 1 ? "" : "s"}. Keep the findings that belong in the filing-readiness
        report and remove any that do not apply.
      </p>

      {findings.length === 0 ? (
        <Banner tone="good">
          No consistency defects were found. Approve to finalize a clean readiness report.
        </Banner>
      ) : (
        <ul className="flex flex-col gap-2">
          {findings.map((finding, index) => {
            const isApproved = approved[index];
            return (
              <li
                key={`${finding.check_id}-${index}`}
                className={`rounded-xl border bg-surface p-4 shadow-[0_1px_2px_rgba(28,39,51,0.04)] transition-opacity ${
                  isApproved ? "border-line" : "border-line/60 opacity-55"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Chip tone={severityTone(finding.severity)}>{finding.severity}</Chip>
                      <span className="font-mono text-xs text-ink-faint">{finding.check_id}</span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-ink">{finding.message}</p>
                    {finding.refs.length > 0 && (
                      <ul className="mt-2 flex flex-col gap-1">
                        {finding.refs.map((ref, refIndex) => (
                          <li
                            key={`${ref.kind}-${ref.ref}-${refIndex}`}
                            className="text-xs text-ink-soft"
                          >
                            <span className="font-semibold uppercase tracking-wide text-ink-faint">
                              {ref.kind}
                            </span>{" "}
                            <span className="font-mono">{ref.ref}</span>
                            {ref.excerpt && (
                              <span className="italic text-ink-faint"> — “{ref.excerpt}”</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <Button
                    variant={isApproved ? "secondary" : "ghost"}
                    onClick={() => toggle(index)}
                    className="shrink-0"
                  >
                    {isApproved ? "Remove" : "Restore"}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {submitError && <Banner tone="danger">{submitError}</Banner>}

      <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
        <span className="text-xs text-ink-faint">
          {approvedFindings.length} of {findings.length} findings kept
        </span>
        <Button isBusy={isSubmitting} onClick={() => onSubmit(approvedFindings)}>
          Approve findings and finalize report
        </Button>
      </div>
    </div>
  );
}
