"use client";

import { CriterionCard } from "@/components/screener/CriterionCard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import {
  CRITERIA_THRESHOLD,
  type CriterionVerdict,
  type FinalMeritsAssessment,
  type ProfileSummary,
  type ProfileVerification,
  type ScreenerReport,
  type VerificationStatus,
  type VisaVerdict,
} from "@/lib/screener/types";

const RECOMMENDATION_BADGE: Record<VisaVerdict["recommendation"], string> = {
  strong: "bg-good text-white",
  possible: "bg-accent-wash text-accent-deep border border-accent/30",
  weak: "bg-warn-wash text-warn border border-warn/30",
  not_recommended: "bg-danger-wash text-danger border border-danger/30",
};

const RECOMMENDATION_LABEL: Record<VisaVerdict["recommendation"], string> = {
  strong: "Strong",
  possible: "Possible",
  weak: "Weak",
  not_recommended: "Not recommended",
};

const VISA_NAMES: Record<string, string> = {
  O1A: "O-1A",
  EB1A: "EB-1A",
};

const VERDICT_ORDER: Record<CriterionVerdict, number> = {
  met: 0,
  likely: 1,
  weak: 2,
  not_met: 3,
};

const MERITS_TONE: Record<FinalMeritsAssessment["conclusion"], "good" | "warn" | "danger"> = {
  favorable: "good",
  uncertain: "warn",
  unfavorable: "danger",
};

const SUMMARY_TONE = {
  good: { title: "text-good", marker: "text-good" },
  accent: { title: "text-accent-deep", marker: "text-accent" },
  warn: { title: "text-warn", marker: "text-warn" },
} as const;

function SummaryList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: keyof typeof SUMMARY_TONE;
}) {
  const styles = SUMMARY_TONE[tone];
  return (
    <div className={tone === "warn" ? "rounded-lg bg-warn-wash p-3" : "p-3"}>
      <p className={`text-[11px] font-semibold uppercase tracking-[0.14em] ${styles.title}`}>
        {title}
      </p>
      {items.length === 0 ? (
        <p className="mt-1.5 text-xs text-ink-faint">None identified.</p>
      ) : (
        <ul className="mt-1.5 space-y-1.5 text-xs leading-relaxed text-ink-soft">
          {items.map((item) => (
            <li key={item} className="flex gap-1.5">
              <span aria-hidden className={`shrink-0 font-semibold ${styles.marker}`}>
                {tone === "warn" ? "!" : "•"}
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProfileSummaryCard({ summary }: { summary: ProfileSummary }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
        Profile summary
      </p>
      <h3 className="mt-2 max-w-3xl font-display text-2xl leading-snug tracking-tight">
        {summary.headline}
      </h3>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <SummaryList title="Strengths" items={summary.strengths} tone="good" />
        <SummaryList
          title="What makes you eligible"
          items={summary.eligibility_drivers}
          tone="accent"
        />
        <SummaryList title="What will bounce back" items={summary.risks} tone="warn" />
      </div>
      {summary.verification_note !== "" && (
        <p className="mt-4 border-t border-line pt-3 text-xs leading-relaxed text-ink-faint">
          {summary.verification_note}
        </p>
      )}
    </div>
  );
}

const IDENTITY_BADGE: Record<ProfileVerification["identity_confidence"], string> = {
  high: "bg-good-wash text-good border border-good/30",
  medium: "bg-warn-wash text-warn border border-warn/30",
  low: "bg-danger-wash text-danger border border-danger/30",
};

const STATUS_CHIP: Record<VerificationStatus, string> = {
  verified: "bg-good-wash text-good border border-good/30",
  partially_verified: "bg-warn-wash text-warn border border-warn/30",
  unverified: "bg-paper text-ink-soft border border-line-strong",
  contradicted: "bg-danger-wash text-danger border border-danger/30",
};

const STATUS_LABEL: Record<VerificationStatus, string> = {
  verified: "Verified",
  partially_verified: "Partially verified",
  unverified: "Unverified",
  contradicted: "Contradicted",
};

/** Evidence links read as their host; the full URL stays in the href. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function VerificationRow({ verification }: { verification: ProfileVerification["verifications"][number] }) {
  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CHIP[verification.status]}`}
        >
          {STATUS_LABEL[verification.status]}
        </span>
        <span className="text-sm leading-relaxed text-ink">{verification.claim}</span>
      </div>
      {verification.evidence_urls.length > 0 && (
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
          {verification.evidence_urls.map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-deep underline decoration-accent/40 underline-offset-2 transition-colors hover:decoration-accent"
            >
              {hostOf(url)}
            </a>
          ))}
        </p>
      )}
      {verification.notes !== "" && (
        <p className="mt-1 text-xs leading-relaxed text-ink-soft">{verification.notes}</p>
      )}
    </li>
  );
}

function VerificationBlock({ verification }: { verification: ProfileVerification }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
          Online verification
        </p>
        <span
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${IDENTITY_BADGE[verification.identity_confidence]}`}
        >
          {verification.identity_confidence} identity confidence
        </span>
      </div>

      {verification.verifications.length === 0 ? (
        <p className="mt-3 text-sm text-ink-soft">
          No claims could be checked against public sources this run.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {verification.verifications.map((v) => (
            <VerificationRow key={v.claim} verification={v} />
          ))}
        </ul>
      )}

      {verification.searched_but_absent.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="text-xs text-ink-faint">We looked for these and found nothing:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-ink-faint">
            {verification.searched_but_absent.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-3 text-[11px] text-ink-faint">
        {verification.tool_calls_used} tool call
        {verification.tool_calls_used === 1 ? "" : "s"} used · every evidence link points at a page
        the agent actually saw.
      </p>
    </div>
  );
}

function VerdictCard({ verdict }: { verdict: VisaVerdict }) {
  const meetsThreshold = verdict.criteria_met >= CRITERIA_THRESHOLD;
  return (
    <div className="flex-1 rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-display text-2xl tracking-tight">
          {VISA_NAMES[verdict.visa] ?? verdict.visa}
        </h3>
        <span
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${RECOMMENDATION_BADGE[verdict.recommendation]}`}
        >
          {RECOMMENDATION_LABEL[verdict.recommendation]}
        </span>
        <span className="text-xs text-ink-faint">{verdict.confidence} confidence</span>
      </div>

      <p className="mt-3 font-display text-4xl">
        {verdict.criteria_met}
        <span className="text-base text-ink-faint">
          {" "}of {CRITERIA_THRESHOLD} required criteria met
        </span>
      </p>
      <p className={`text-xs ${meetsThreshold ? "text-good" : "text-ink-soft"}`}>
        {meetsThreshold
          ? "Regulatory threshold reached"
          : `${verdict.criteria_likely} more likely with stronger documentation`}
      </p>

      {verdict.summary && (
        <p className="mt-3 text-sm leading-relaxed text-ink-soft">{verdict.summary}</p>
      )}

      {verdict.next_steps.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
            Next steps
          </p>
          <ol className="mt-1 list-decimal space-y-1 pl-4 text-xs leading-relaxed text-ink-soft">
            {verdict.next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

type Props = {
  report: ScreenerReport;
  onRestart: () => void;
};

export function ReportStep({ report, onRestart }: Props) {
  const sortedAssessments = [...report.assessments].sort(
    (a, b) => VERDICT_ORDER[a.verdict] - VERDICT_ORDER[b.verdict],
  );

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Screening report.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Every verdict below was audited: a citation that does not point at something you actually
          provided was stripped, and uncited verdicts were downgraded. Insufficient evidence is a
          finding, not a failure.
        </p>
      </header>

      {report.warnings.length > 0 && (
        <Banner tone="warn">
          <strong className="font-semibold">
            {report.warnings.length} warning{report.warnings.length === 1 ? "" : "s"} from this run:
          </strong>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {report.warnings.map((w) => (
              <li key={`${w.field}-${w.message}`}>{w.message}</li>
            ))}
          </ul>
        </Banner>
      )}

      {report.profile_summary && <ProfileSummaryCard summary={report.profile_summary} />}

      {report.verification && <VerificationBlock verification={report.verification} />}

      {report.verdicts.length === 0 ? (
        <Banner tone="danger">
          No visa verdict could be produced for this run — see the warnings above and re-run.
        </Banner>
      ) : (
        <div className="flex flex-wrap gap-4">
          {report.verdicts.map((verdict) => (
            <VerdictCard key={verdict.visa} verdict={verdict} />
          ))}
        </div>
      )}

      {report.final_merits && (
        <div className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
          <div className="flex flex-wrap items-baseline gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
              Final merits (EB-1A · Kazarian step 2)
            </p>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                MERITS_TONE[report.final_merits.conclusion] === "good"
                  ? "bg-good-wash text-good border border-good/30"
                  : MERITS_TONE[report.final_merits.conclusion] === "warn"
                    ? "bg-warn-wash text-warn border border-warn/30"
                    : "bg-danger-wash text-danger border border-danger/30"
              }`}
            >
              {report.final_merits.conclusion}
            </span>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-ink-soft">
            {report.final_merits.reasoning}
          </p>
        </div>
      )}

      <div>
        <h3 className="font-display text-xl tracking-tight">Criterion by criterion</h3>
        <p className="mt-1 text-sm text-ink-soft">
          Sorted strongest first. Expand the citations to see exactly what each verdict rests on.
        </p>
        <ul className="mt-3 flex flex-col gap-3">
          {sortedAssessments.map((assessment) => (
            <CriterionCard key={assessment.criterion_id} assessment={assessment} />
          ))}
        </ul>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onRestart}>
          Start a new screening
        </Button>
        <p className="text-xs text-ink-faint">
          Session {report.session_id.slice(0, 8)} · findings require attorney review before any
          filing decision.
        </p>
      </footer>
    </section>
  );
}
