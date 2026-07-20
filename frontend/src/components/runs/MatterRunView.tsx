"use client";

import Link from "next/link";

import { InterruptPanel } from "@/components/runs/InterruptPanel";
import { RunReport } from "@/components/runs/RunReport";
import { StageChecklist, type StageState } from "@/components/runs/StageChecklist";
import { Banner } from "@/components/ui/Banner";
import { RunStatusChip } from "@/components/ui/Chip";
import { ApiError } from "@/lib/api";
import { useInbox, usePackages, useResumeRun, useRun } from "@/lib/matters/queries";
import type { Interrupt, RunStatus, StageSummary, WorkflowRun } from "@/lib/matters/types";

type Props = { matterId: string; runId: string };

/**
 * Stage state for a matter-store run. Coarse in v1 (no per-node telemetry): a
 * done run marks every stage complete; an awaiting_input run marks the review
 * stage active and prior stages done; otherwise everything is pending/active.
 */
function stageStateFor(
  stages: StageSummary[],
  stageId: string,
  status: RunStatus,
): StageState {
  if (status === "done") return "done";
  const reviewIndex = stages.findIndex(
    (s) => s.id === "review" || s.nodes.includes("review_gate"),
  );
  const index = stages.findIndex((s) => s.id === stageId);
  if (status === "awaiting_input" && reviewIndex !== -1) {
    if (index < reviewIndex) return "done";
    if (index === reviewIndex) return "active";
    return "pending";
  }
  if (status === "running" || status === "queued") {
    return index === 0 ? "active" : "pending";
  }
  return "pending";
}

function findInterrupt(interrupts: Interrupt[], runId: string): Interrupt | null {
  return interrupts.find((i) => i.run_id === runId && i.status === "pending") ?? null;
}

export function MatterRunView({ matterId, runId }: Props) {
  const runQuery = useRun(runId);
  const inbox = useInbox();
  const packages = usePackages();
  const resume = useResumeRun(runId);

  if (runQuery.isLoading) {
    return <p className="text-sm text-ink-soft">Loading run…</p>;
  }

  if (runQuery.isError || !runQuery.data) {
    return (
      <div className="flex flex-col gap-4">
        <Link href={`/matters/${matterId}`} className="text-sm text-accent-deep hover:underline">
          ← Matter
        </Link>
        <Banner tone="danger">
          {runQuery.error instanceof ApiError
            ? runQuery.error.message
            : "Could not load this run."}
        </Banner>
      </div>
    );
  }

  const run: WorkflowRun = runQuery.data.run;
  const artifacts = runQuery.data.artifacts;
  const manifest = packages.data?.packages.find((p) => p.package_id === run.package_id);
  const stages = manifest?.stages ?? [];
  const interrupt = findInterrupt(inbox.data?.interrupts ?? [], runId);

  const submitError =
    resume.error instanceof ApiError
      ? resume.error.message
      : resume.isError
        ? "Could not resume the run."
        : null;

  return (
    <div className="flex flex-col gap-8 lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <div className="flex flex-col gap-2">
          <Link href={`/matters/${matterId}`} className="w-fit text-sm text-accent-deep hover:underline">
            ← Matter
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display text-3xl tracking-tight">
              {manifest?.title ?? run.package_id}
            </h1>
            <RunStatusChip status={run.status} />
          </div>
        </div>

        {(run.status === "queued" || run.status === "running") && (
          <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-5">
            <span
              aria-hidden
              className="size-5 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent"
            />
            <p className="text-sm text-ink-soft" role="status">
              The workflow is running. This view updates automatically.
            </p>
          </div>
        )}

        {run.status === "error" && (
          <Banner tone="danger">This run ended in an error. Check the backend logs.</Banner>
        )}

        {run.status === "awaiting_input" &&
          (interrupt ? (
            <InterruptPanel
              kind={interrupt.kind}
              payload={interrupt.payload_json}
              isSubmitting={resume.isPending}
              submitError={submitError}
              onExtractionSubmit={(r) => resume.mutate({ passport: r.passport, g28: r.g28 })}
              onPreflightSubmit={(findings) => resume.mutate({ findings })}
            />
          ) : (
            <Banner tone="warn">
              This run is awaiting input, but its review checkpoint could not be found in the inbox.
              Reload to retry.
            </Banner>
          ))}

        {run.status === "done" && (
          <section className="flex flex-col gap-4">
            <h2 className="font-display text-xl tracking-tight">Result</h2>
            <RunReport report={run.summary_json?.report ?? run.summary_json ?? null} />
            {artifacts.length > 0 && (
              <ul className="divide-y divide-line rounded-xl border border-line bg-surface text-sm">
                {artifacts.map((artifact) => (
                  <li
                    key={artifact.id}
                    className="flex items-center justify-between gap-3 px-5 py-3"
                  >
                    <span className="text-ink">{artifact.kind}</span>
                    <span className="font-mono text-xs text-ink-faint">
                      {artifact.artifact_ref.slice(0, 12)}…
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>

      <aside className="w-full shrink-0 lg:w-64">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
          Stages
        </p>
        <StageChecklist
          stages={stages}
          stateFor={(stageId) => stageStateFor(stages, stageId, run.status)}
        />
      </aside>
    </div>
  );
}
