"use client";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { getApiBase, HUMAN_NOTE } from "@/lib/config";
import type { PopulationEntry, PopulationReport } from "@/lib/types";

type Props = {
  report: PopulationReport;
  onBackToReview: () => void;
  onRestart: () => void;
};

type ChipTone = "good" | "neutral" | "danger";

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: ChipTone;
}) {
  const toneClass =
    tone === "good"
      ? "border-good/30 bg-good-wash"
      : tone === "danger"
        ? "border-danger/40 bg-danger-wash"
        : "border-line bg-surface";
  const numberClass =
    tone === "good" ? "text-good" : tone === "danger" ? "text-danger" : "text-ink";
  return (
    <div className={`flex-1 rounded-xl border px-4 py-3 ${toneClass}`}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">{label}</p>
      <p className={`mt-1 font-display text-4xl ${numberClass}`}>{value}</p>
    </div>
  );
}

const STATUS_BADGE: Record<PopulationEntry["status"], string> = {
  filled: "bg-good-wash text-good",
  skipped_null: "bg-line/60 text-ink-faint",
  mismatch: "bg-danger text-white",
  error: "bg-danger text-white",
};

const STATUS_LABEL: Record<PopulationEntry["status"], string> = {
  filled: "filled",
  skipped_null: "skipped (null)",
  mismatch: "MISMATCH",
  error: "ERROR",
};

function EntryRow({ entry }: { entry: PopulationEntry }) {
  const isLoud = entry.status === "mismatch" || entry.status === "error";
  return (
    <tr
      className={
        isLoud
          ? "border-l-4 border-l-danger bg-danger-wash/70"
          : entry.status === "skipped_null"
            ? "text-ink-faint"
            : ""
      }
    >
      <td className="px-4 py-2 font-mono text-xs">{entry.selector}</td>
      <td className="px-4 py-2 font-mono text-xs text-ink-soft">{entry.source}</td>
      <td className="px-4 py-2 text-xs">{entry.action}</td>
      <td className="px-4 py-2">
        <span
          className={`inline-block rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${STATUS_BADGE[entry.status]}`}
        >
          {STATUS_LABEL[entry.status]}
        </span>
      </td>
      <td className="px-4 py-2 font-mono text-xs">{entry.expected ?? "—"}</td>
      <td className={`px-4 py-2 font-mono text-xs ${isLoud ? "font-semibold text-danger" : ""}`}>
        {entry.actual ?? "—"}
      </td>
    </tr>
  );
}

export function ReportStage({ report, onBackToReview, onRestart }: Props) {
  const issueCount = report.mismatches + report.errors;

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Population report</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Every field was read back from the form after filling and compared to what was sent.
          {" "}{HUMAN_NOTE}
        </p>
      </header>

      {report.ok ? (
        <Banner tone="good">
          <strong className="font-semibold">Verified.</strong> All filled fields read back exactly
          as sent. Target:{" "}
          <a
            className="underline underline-offset-2"
            href={report.target_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {report.target_url}
          </a>
        </Banner>
      ) : (
        <Banner tone="danger">
          <strong className="font-semibold">
            Do not trust this fill — {issueCount} field{issueCount === 1 ? "" : "s"} did not verify.
          </strong>{" "}
          The rows marked below read back differently than expected or failed outright. Check
          them against the captured copy of the filled form before going further. Target:{" "}
          <a
            className="underline underline-offset-2"
            href={report.target_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {report.target_url}
          </a>
        </Banner>
      )}

      <div className="flex flex-wrap gap-3">
        <StatChip label="Filled" value={report.filled} tone="good" />
        <StatChip label="Skipped (no value)" value={report.skipped_null} tone="neutral" />
        <StatChip
          label="Mismatches"
          value={report.mismatches}
          tone={report.mismatches > 0 ? "danger" : "neutral"}
        />
        <StatChip
          label="Errors"
          value={report.errors}
          tone={report.errors > 0 ? "danger" : "neutral"}
        />
      </div>

      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
        <table className="w-full min-w-[46rem] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-[11px] uppercase tracking-[0.1em] text-ink-faint">
              <th className="px-4 py-3 font-semibold">Selector</th>
              <th className="px-4 py-3 font-semibold">Source</th>
              <th className="px-4 py-3 font-semibold">Action</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3 font-semibold">Expected</th>
              <th className="px-4 py-3 font-semibold">Read back</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {report.entries.map((entry, i) => (
              <EntryRow key={`${entry.selector}-${i}`} entry={entry} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-ink-faint">{HUMAN_NOTE}</p>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={onRestart}>
          Start over
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" onClick={onBackToReview}>
            Back to review
          </Button>
          {report.artifact_id && (
            <>
              <a
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-line-strong bg-surface px-5 py-2.5 text-sm font-medium text-ink transition-colors duration-150 hover:border-accent hover:text-accent-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                href={`${getApiBase()}/api/population-artifact/${report.artifact_id}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                View filled form
              </a>
              <a
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-accent-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                href={`${getApiBase()}/api/population-artifact/${report.artifact_id}?download=1`}
              >
                Download ({report.artifact_kind === "png" ? "image" : "PDF"})
              </a>
            </>
          )}
        </div>
      </footer>
    </section>
  );
}
