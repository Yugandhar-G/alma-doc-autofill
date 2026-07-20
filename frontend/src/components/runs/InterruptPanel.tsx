"use client";

import Link from "next/link";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import type { G28Data, PassportData } from "@/lib/types";
import type { PreflightFinding } from "@/lib/matters/types";

import { ExtractionReviewPanel } from "./ExtractionReviewPanel";
import { PreflightReviewPanel } from "./PreflightReviewPanel";

/**
 * Dispatches a parked run's human-review interrupt to the right editor by its
 * kind. The panel owns only presentation + the submit shape; the caller wires
 * the kind-appropriate resume endpoint (autofill vs preflight) via the
 * callbacks. `matrix_review` is intentionally a link-out to the legacy screener
 * flow — that experience is not rebuilt here.
 */
type Props = {
  kind: string;
  payload: Record<string, unknown>;
  onExtractionSubmit?: (resume: { passport: PassportData | null; g28: G28Data | null }) => void;
  onPreflightSubmit?: (findings: PreflightFinding[]) => void;
  isSubmitting?: boolean;
  submitError?: string | null;
};

const noop = () => {};

function PanelShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-warn/30 bg-warn-wash/40 p-5 sm:p-6">
      <header className="mb-4 flex items-center gap-2">
        <span aria-hidden className="size-2 rounded-full bg-warn" />
        <h2 className="font-display text-xl tracking-tight">{title}</h2>
      </header>
      {children}
    </section>
  );
}

export function InterruptPanel({
  kind,
  payload,
  onExtractionSubmit,
  onPreflightSubmit,
  isSubmitting,
  submitError,
}: Props) {
  switch (kind) {
    case "extraction_review":
      return (
        <PanelShell title="Review extracted data">
          <ExtractionReviewPanel
            payload={payload}
            onSubmit={onExtractionSubmit ?? noop}
            isSubmitting={isSubmitting}
            submitError={submitError}
          />
        </PanelShell>
      );

    case "preflight_review":
      return (
        <PanelShell title="Review pre-flight findings">
          <PreflightReviewPanel
            payload={payload}
            onSubmit={onPreflightSubmit ?? noop}
            isSubmitting={isSubmitting}
            submitError={submitError}
          />
        </PanelShell>
      );

    case "matrix_review":
      return (
        <PanelShell title="Review the evidence matrix">
          <p className="text-sm leading-relaxed text-ink-soft">
            This run parked at the screener&apos;s evidence-matrix review. That review lives in the
            dedicated screener workspace, where every claim is shown with its sources before
            verification runs.
          </p>
          <div className="mt-4">
            <Link href="/screener">
              <Button variant="primary">Open the screener review</Button>
            </Link>
          </div>
        </PanelShell>
      );

    default:
      return (
        <PanelShell title="Human review required">
          <Banner tone="info">
            This run is paused for a “{kind}” review, which has no specialized editor in this
            workspace yet. Inspect the run payload below and resume from the tool that raised it.
          </Banner>
          <pre className="mt-4 max-h-64 overflow-auto rounded-lg border border-line bg-surface p-3 text-xs text-ink-soft">
            {JSON.stringify(payload, null, 2)}
          </pre>
        </PanelShell>
      );
  }
}
