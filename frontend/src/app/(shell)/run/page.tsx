"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { RunRouter } from "@/components/runs/RunRouter";
import { Banner } from "@/components/ui/Banner";

/**
 * Static twin of `/matters/[id]/runs/[runId]` for the desktop export. Renders
 * the same RunRouter, sourcing matterId + runId from the query string (`pkg`
 * is read by RunRouter itself). Static so it exports cleanly.
 */
function RunTwin() {
  const params = useSearchParams();
  const matterId = params.get("matterId");
  const runId = params.get("runId");
  if (!matterId || !runId) {
    return <Banner tone="danger">This link is missing its run identifiers.</Banner>;
  }
  return <RunRouter matterId={matterId} runId={runId} />;
}

export default function RunQueryPage() {
  return (
    <Suspense fallback={<p className="text-sm text-ink-soft">Loading run…</p>}>
      <RunTwin />
    </Suspense>
  );
}
