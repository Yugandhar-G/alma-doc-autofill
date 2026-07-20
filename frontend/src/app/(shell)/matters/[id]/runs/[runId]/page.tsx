"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { MatterRunView } from "@/components/runs/MatterRunView";
import { PackageRunView } from "@/components/runs/PackageRunView";
import { launchKind } from "@/lib/matters/packages";

function RunViewSwitch() {
  const params = useParams<{ id: string; runId: string }>();
  const searchParams = useSearchParams();
  const pkg = searchParams.get("pkg");

  // A `pkg` query param marks a self-routed run (autofill/preflight), whose
  // status/resume go through the package router. Everything else is a
  // matter-store run reached via /api/runs/{id}.
  if (pkg && launchKind(pkg) === "package_upload") {
    return <PackageRunView matterId={params.id} packageId={pkg} runId={params.runId} />;
  }
  return <MatterRunView matterId={params.id} runId={params.runId} />;
}

export default function RunPage() {
  return (
    <Suspense fallback={<p className="text-sm text-ink-soft">Loading run…</p>}>
      <RunViewSwitch />
    </Suspense>
  );
}
