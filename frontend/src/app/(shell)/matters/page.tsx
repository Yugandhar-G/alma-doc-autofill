"use client";

import { Banner } from "@/components/ui/Banner";
import { EmptyState } from "@/components/ui/EmptyState";
import { MattersTable } from "@/components/matters/MattersTable";
import { NewMatterForm } from "@/components/matters/NewMatterForm";
import { ApiError } from "@/lib/api";
import { useMatters, usePackages } from "@/lib/matters/queries";

export default function MattersPage() {
  const matters = useMatters();
  const packages = usePackages();

  const rows = matters.data?.matters ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl tracking-tight">Matters</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Every case file in the firm and where its workflows stand.
          </p>
        </div>
        <NewMatterForm packages={packages.data?.packages ?? []} />
      </header>

      {matters.isError && (
        <Banner tone="danger">
          {matters.error instanceof ApiError
            ? matters.error.message
            : "Could not load matters."}
        </Banner>
      )}

      {matters.isLoading ? (
        <p className="text-sm text-ink-soft">Loading matters…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No matters yet"
          description="Create the first matter to start uploading documents and running workflows against it."
        />
      ) : (
        <MattersTable matters={rows} />
      )}
    </div>
  );
}
