"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { MatterDetailView } from "@/components/matters/MatterDetailView";
import { Banner } from "@/components/ui/Banner";

/**
 * Static twin of `/matters/[id]` for the desktop export. Renders the same
 * MatterDetailView, sourcing the matter id from `?id=` instead of a route
 * param. Static (no dynamic segment) so it exports cleanly.
 */
function MatterTwin() {
  const id = useSearchParams().get("id");
  if (!id) {
    return <Banner tone="danger">This link is missing a matter id.</Banner>;
  }
  return <MatterDetailView matterId={id} />;
}

export default function MatterQueryPage() {
  return (
    <Suspense fallback={<p className="text-sm text-ink-soft">Loading matter…</p>}>
      <MatterTwin />
    </Suspense>
  );
}
