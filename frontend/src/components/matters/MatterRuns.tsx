"use client";

import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/ui/EmptyState";
import { RunStatusChip } from "@/components/ui/Chip";
import { formatDateTime } from "@/lib/matters/format";
import type { PackageManifestSummary, WorkflowRun } from "@/lib/matters/types";

type Props = {
  matterId: string;
  runs: WorkflowRun[];
  packages: PackageManifestSummary[];
};

/**
 * Matter-store runs (state-only packages started via the matter path). Runs
 * launched through a package's own multipart endpoint — autofill/preflight —
 * do not mint matter-store rows, so they surface at their own run view rather
 * than in this list.
 */
export function MatterRuns({ matterId, runs, packages }: Props) {
  const router = useRouter();
  const titleFor = (packageId: string) =>
    packages.find((p) => p.package_id === packageId)?.title ?? packageId;

  if (runs.length === 0) {
    return (
      <EmptyState
        title="No workflow runs yet"
        description="Start a workflow below to run a package against this matter."
      />
    );
  }

  return (
    <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
      {runs.map((run) => (
        <li key={run.id}>
          <button
            type="button"
            onClick={() => router.push(`/matters/${matterId}/runs/${run.id}`)}
            className="flex w-full items-center justify-between gap-4 px-5 py-3.5 text-left transition-colors hover:bg-accent-wash/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">{titleFor(run.package_id)}</p>
              <p className="text-xs text-ink-faint">Started {formatDateTime(run.created_at)}</p>
            </div>
            <RunStatusChip status={run.status} />
          </button>
        </li>
      ))}
    </ul>
  );
}
