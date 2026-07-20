"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { InterruptPanel } from "@/components/runs/InterruptPanel";
import { RunReport } from "@/components/runs/RunReport";
import { StageChecklist, type StageState } from "@/components/runs/StageChecklist";
import { Banner } from "@/components/ui/Banner";
import { ApiError } from "@/lib/api";
import { resumeAutofillRun, resumePreflightRun } from "@/lib/matters/api";
import { packageInterruptKind } from "@/lib/matters/packages";
import { packageRunKeys, usePackageRun, usePackages } from "@/lib/matters/queries";
import type { PreflightFinding, StageSummary } from "@/lib/matters/types";
import type { G28Data, PassportData } from "@/lib/types";

type Props = { matterId: string; packageId: string; runId: string };

/** Stage state for a self-routed run: review is the parked point. */
function stageStateFor(stages: StageSummary[], stageId: string, done: boolean): StageState {
  if (done) return "done";
  const reviewIndex = stages.findIndex(
    (s) => s.id === "review" || s.nodes.includes("review_gate"),
  );
  const index = stages.findIndex((s) => s.id === stageId);
  if (reviewIndex === -1) return "pending";
  if (index < reviewIndex) return "done";
  if (index === reviewIndex) return "active";
  return "pending";
}

export function PackageRunView({ matterId, packageId, runId }: Props) {
  const queryClient = useQueryClient();
  const status = usePackageRun(packageId, runId);
  const packages = usePackages();

  // Snapshot the parked-review payload carried from the start response. Absent
  // on a hard reload — see the reload banner below.
  const [startPayload] = useState<Record<string, unknown> | undefined>(() =>
    queryClient.getQueryData(packageRunKeys.startPayload(runId)),
  );

  const resume = useMutation({
    mutationFn: async (resumeInput:
      | { kind: "extraction"; passport: PassportData | null; g28: G28Data | null }
      | { kind: "preflight"; findings: PreflightFinding[] }) => {
      if (resumeInput.kind === "extraction") {
        return resumeAutofillRun(runId, { passport: resumeInput.passport, g28: resumeInput.g28 });
      }
      return resumePreflightRun(runId, resumeInput.findings);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: packageRunKeys.status(packageId, runId) });
    },
  });

  const manifest = packages.data?.packages.find((p) => p.package_id === packageId);
  const stages = manifest?.stages ?? [];
  const runStatus = status.data?.status;
  const isDone = runStatus === "done";

  const submitError =
    resume.error instanceof ApiError
      ? resume.error.message
      : resume.isError
        ? "Could not resume the run."
        : null;

  return (
    <div className="flex flex-col gap-8 lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <RunHeader matterId={matterId} title={manifest?.title ?? packageId} />

        {status.isLoading && <p className="text-sm text-ink-soft">Loading run…</p>}

        {status.isError && (
          <Banner tone="danger">
            {status.error instanceof ApiError
              ? status.error.message
              : "Could not load this run."}
          </Banner>
        )}

        {runStatus === "awaiting_review" && startPayload && (
          <InterruptPanel
            kind={packageInterruptKind(packageId)}
            payload={
              packageId === "preflight"
                ? { report: startPayload.report }
                : { passport: startPayload.passport ?? null, g28: startPayload.g28 ?? null }
            }
            isSubmitting={resume.isPending}
            submitError={submitError}
            onExtractionSubmit={(r) =>
              resume.mutate({ kind: "extraction", passport: r.passport, g28: r.g28 })
            }
            onPreflightSubmit={(findings) => resume.mutate({ kind: "preflight", findings })}
          />
        )}

        {runStatus === "awaiting_review" && !startPayload && (
          <Banner tone="warn">
            This run is awaiting review, but its review data was not carried into this page (it is
            held in memory from the moment the run started and is lost on a full reload). Start the
            workflow again from the matter to review it.
          </Banner>
        )}

        {isDone && (
          <section className="flex flex-col gap-4">
            <h2 className="font-display text-xl tracking-tight">Result</h2>
            <RunReport report={status.data?.report ?? null} />
          </section>
        )}
      </div>

      <aside className="w-full shrink-0 lg:w-64">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
          Stages
        </p>
        <StageChecklist
          stages={stages}
          stateFor={(stageId) => stageStateFor(stages, stageId, isDone)}
        />
      </aside>
    </div>
  );
}

function RunHeader({ matterId, title }: { matterId: string; title: string }) {
  return (
    <div className="flex flex-col gap-2">
      <Link href={`/matters/${matterId}`} className="w-fit text-sm text-accent-deep hover:underline">
        ← Matter
      </Link>
      <h1 className="font-display text-3xl tracking-tight">{title}</h1>
    </div>
  );
}
