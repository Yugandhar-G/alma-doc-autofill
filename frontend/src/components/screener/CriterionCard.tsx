"use client";

import { useState } from "react";

import {
  criterionLabel,
  type CriterionAssessment,
  type CriterionVerdict,
  type SourceRef,
} from "@/lib/screener/types";

export const VERDICT_BADGE: Record<CriterionVerdict, string> = {
  met: "bg-good text-white",
  likely: "bg-good-wash text-good border border-good/30",
  weak: "bg-warn-wash text-warn border border-warn/30",
  not_met: "bg-line/60 text-ink-faint",
};

export const VERDICT_LABEL: Record<CriterionVerdict, string> = {
  met: "Met",
  likely: "Likely",
  weak: "Weak",
  not_met: "Not met",
};

const SOURCE_KIND_CLASS: Record<SourceRef["kind"], string> = {
  answer: "border-accent/30 bg-accent-wash text-accent-deep",
  doc: "border-line-strong bg-paper text-ink-soft",
  web: "border-good/30 bg-good-wash text-good",
};

function CitationLine({ citation }: { citation: SourceRef }) {
  const preview =
    citation.kind === "doc"
      ? citation.ref.slice(0, 12)
      : citation.ref.length > 72
        ? `${citation.ref.slice(0, 72)}…`
        : citation.ref;
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span
        className={`rounded-full border px-1.5 py-px text-[10px] font-semibold uppercase tracking-[0.1em] ${SOURCE_KIND_CLASS[citation.kind]}`}
      >
        {citation.kind}
      </span>
      <span className="break-all font-mono text-xs text-ink-soft" title={citation.ref}>
        {preview}
      </span>
      {citation.excerpt && (
        <span className="w-full text-xs italic leading-relaxed text-ink-faint">
          &ldquo;{citation.excerpt}&rdquo;
        </span>
      )}
    </li>
  );
}

type Props = {
  assessment: CriterionAssessment;
};

export function CriterionCard({ assessment }: Props) {
  const [showCitations, setShowCitations] = useState(false);

  return (
    <li className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${VERDICT_BADGE[assessment.verdict]}`}
        >
          {VERDICT_LABEL[assessment.verdict]}
        </span>
        <h4 className="font-display text-lg">{criterionLabel(assessment.criterion_id)}</h4>
      </div>

      <p className="mt-2 text-sm leading-relaxed text-ink-soft">{assessment.reasoning}</p>

      {assessment.citations.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            aria-expanded={showCitations}
            onClick={() => setShowCitations((v) => !v)}
            className="rounded px-1 py-0.5 text-xs font-medium text-accent-deep transition-colors hover:bg-accent-wash focus-visible:outline-2 focus-visible:outline-accent"
          >
            {showCitations ? "Hide" : "Show"} {assessment.citations.length} citation
            {assessment.citations.length === 1 ? "" : "s"}
          </button>
          {showCitations && (
            <ul className="mt-2 space-y-1.5 rounded-lg border border-line bg-paper/50 p-3">
              {assessment.citations.map((citation, i) => (
                <CitationLine key={`${citation.kind}-${citation.ref}-${i}`} citation={citation} />
              ))}
            </ul>
          )}
        </div>
      )}

      {(assessment.gaps.length > 0 || assessment.rfe_risks.length > 0) && (
        <div className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
          {assessment.gaps.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
                Gaps
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs leading-relaxed text-ink-soft">
                {assessment.gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </div>
          )}
          {assessment.rfe_risks.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-warn">
                RFE risks
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs leading-relaxed text-warn">
                {assessment.rfe_risks.map((risk) => (
                  <li key={risk}>{risk}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
