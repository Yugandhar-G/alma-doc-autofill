"use client";

import { useSearchParams } from "next/navigation";

import { MatterRunView } from "@/components/runs/MatterRunView";
import { PackageRunView } from "@/components/runs/PackageRunView";
import { launchKind } from "@/lib/matters/packages";

type Props = { matterId: string; runId: string };

/**
 * Run screen body, shared by the web dynamic route
 * (`/matters/[id]/runs/[runId]`) and the desktop static twin (`/run?...`).
 *
 * A `pkg` query param marks a self-routed run (autofill/preflight), whose
 * status/resume go through the package router. Everything else is a
 * matter-store run reached via /api/runs/{id}. `pkg` is read from the query on
 * both surfaces, so the caller only needs to supply matterId + runId. Must be
 * rendered inside a Suspense boundary (useSearchParams).
 */
export function RunRouter({ matterId, runId }: Props) {
  const pkg = useSearchParams().get("pkg");

  if (pkg && launchKind(pkg) === "package_upload") {
    return <PackageRunView matterId={matterId} packageId={pkg} runId={runId} />;
  }
  return <MatterRunView matterId={matterId} runId={runId} />;
}
