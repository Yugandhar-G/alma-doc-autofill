"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { MatterDocuments } from "@/components/matters/MatterDocuments";
import { MatterRuns } from "@/components/matters/MatterRuns";
import { StartWorkflow } from "@/components/matters/StartWorkflow";
import { Banner } from "@/components/ui/Banner";
import { Chip } from "@/components/ui/Chip";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/matters/format";
import { useMatter, usePackages } from "@/lib/matters/queries";

export default function MatterDetailPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const detail = useMatter(matterId);
  const packages = usePackages();

  if (detail.isLoading) {
    return <p className="text-sm text-ink-soft">Loading matter…</p>;
  }

  if (detail.isError || !detail.data) {
    return (
      <div className="flex flex-col gap-4">
        <Link href="/matters" className="text-sm text-accent-deep hover:underline">
          ← Matters
        </Link>
        <Banner tone="danger">
          {detail.error instanceof ApiError ? detail.error.message : "Could not load this matter."}
        </Banner>
      </div>
    );
  }

  const { matter, documents, runs } = detail.data;
  const pkgs = packages.data?.packages ?? [];

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Link href="/matters" className="w-fit text-sm text-accent-deep hover:underline">
          ← Matters
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-display text-3xl tracking-tight">{matter.title}</h1>
          <Chip tone={matter.status === "open" ? "accent" : "neutral"}>{matter.status}</Chip>
        </div>
        <p className="text-sm text-ink-soft">
          <Chip tone="neutral">{matter.matter_type}</Chip>
          <span className="ml-3">Opened {formatDate(matter.created_at)}</span>
          {matter.client_ref && <span className="ml-3">Client ref: {matter.client_ref}</span>}
        </p>
      </div>

      <MatterDocuments matterId={matter.id} documents={documents} />

      <section className="flex flex-col gap-4">
        <h2 className="font-display text-xl tracking-tight">Workflow runs</h2>
        <MatterRuns matterId={matter.id} runs={runs} packages={pkgs} />
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="font-display text-xl tracking-tight">Start a workflow</h2>
        {packages.isLoading ? (
          <p className="text-sm text-ink-soft">Loading packages…</p>
        ) : (
          <StartWorkflow matter={matter} packages={pkgs} />
        )}
      </section>
    </div>
  );
}
