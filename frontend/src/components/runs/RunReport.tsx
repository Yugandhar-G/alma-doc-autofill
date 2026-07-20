import { Chip, severityTone } from "@/components/ui/Chip";
import { getApiBase } from "@/lib/config";
import type { PreflightReport } from "@/lib/matters/types";
import type { PopulationReport } from "@/lib/types";

/**
 * Renders a finished run's report. Two shapes reach here: an autofill
 * PopulationReport (has `entries`) or a preflight PreflightReport (has
 * `findings`). The shape is detected structurally so the run view stays
 * package-agnostic.
 */
function isPopulationReport(report: Record<string, unknown>): report is Record<string, unknown> {
  return Array.isArray(report.entries);
}

function isPreflightReport(report: Record<string, unknown>): boolean {
  return Array.isArray(report.findings) && Array.isArray(report.checks_run);
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="font-display text-2xl">{value}</p>
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-soft">{label}</p>
    </div>
  );
}

function PopulationReportView({ report }: { report: PopulationReport }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Filled" value={report.filled} />
        <Stat label="Skipped (null)" value={report.skipped_null} />
        <Stat label="Mismatches" value={report.mismatches} />
        <Stat label="Errors" value={report.errors} />
      </div>
      <p className="text-sm text-ink-soft">
        Target form: <span className="font-mono text-xs">{report.target_url}</span>
      </p>
      {report.artifact_id && report.artifact_kind && (
        <a
          href={`${getApiBase()}/api/population-artifact/${report.artifact_id}?download=true`}
          className="inline-flex w-fit items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Download filled form ({report.artifact_kind.toUpperCase()})
        </a>
      )}
    </div>
  );
}

function PreflightReportView({ report }: { report: PreflightReport }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Chip tone={report.ok ? "good" : "danger"} withDot>
          {report.ok ? "No critical findings" : "Critical findings present"}
        </Chip>
        <span className="text-sm text-ink-soft">
          {report.checks_run.length} checks · {report.docs_examined} documents
        </span>
      </div>
      {report.findings.length === 0 ? (
        <p className="text-sm text-ink-soft">The packet passed every consistency check.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {report.findings.map((finding, index) => (
            <li
              key={`${finding.check_id}-${index}`}
              className="rounded-lg border border-line bg-surface p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={severityTone(finding.severity)}>{finding.severity}</Chip>
                <span className="font-mono text-xs text-ink-faint">{finding.check_id}</span>
              </div>
              <p className="mt-2 text-sm text-ink">{finding.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RunReport({ report }: { report: unknown }) {
  if (report === null || typeof report !== "object") {
    return <p className="text-sm text-ink-soft">This run produced no report.</p>;
  }
  const record = report as Record<string, unknown>;
  if (isPopulationReport(record)) {
    return <PopulationReportView report={report as unknown as PopulationReport} />;
  }
  if (isPreflightReport(record)) {
    return <PreflightReportView report={report as unknown as PreflightReport} />;
  }
  return (
    <pre className="max-h-72 overflow-auto rounded-lg border border-line bg-surface p-3 text-xs text-ink-soft">
      {JSON.stringify(report, null, 2)}
    </pre>
  );
}
