"use client";

import { Banner } from "@/components/ui/Banner";
import { Chip } from "@/components/ui/Chip";
import { Table, type Column } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import { usePackages } from "@/lib/matters/queries";
import type { PackageManifestSummary } from "@/lib/matters/types";

const COLUMNS: Column<PackageManifestSummary>[] = [
  {
    key: "package",
    header: "Package",
    cell: (pkg) => (
      <div className="min-w-0">
        <p className="font-display text-base text-ink">{pkg.title}</p>
        <p className="text-xs text-ink-faint">
          {pkg.package_id} · v{pkg.version}
        </p>
      </div>
    ),
  },
  {
    key: "matter_types",
    header: "Matter types",
    cell: (pkg) => (
      <span className="flex flex-wrap gap-1.5">
        {pkg.matter_types.map((type) => (
          <Chip key={type} tone="neutral">
            {type}
          </Chip>
        ))}
      </span>
    ),
  },
  {
    key: "stages",
    header: "Stages",
    cell: (pkg) => <span className="text-sm text-ink-soft">{pkg.stages.length}</span>,
  },
  {
    key: "interrupts",
    header: "Review points",
    cell: (pkg) => (
      <span className="flex flex-wrap gap-1.5">
        {pkg.interrupt_kinds.length === 0 ? (
          <span className="text-xs text-ink-faint">—</span>
        ) : (
          pkg.interrupt_kinds.map((kind) => (
            <Chip key={kind} tone="accent">
              {kind}
            </Chip>
          ))
        )}
      </span>
    ),
  },
];

export default function PackagesPage() {
  const packages = usePackages();
  const rows = packages.data?.packages ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="font-display text-3xl tracking-tight">Packages</h1>
        <p className="mt-1 text-sm text-ink-soft">
          The workflow packages installed on this firm&apos;s kernel.
        </p>
      </header>

      {packages.isError && (
        <Banner tone="danger">
          {packages.error instanceof ApiError
            ? packages.error.message
            : "Could not load packages."}
        </Banner>
      )}

      {packages.isLoading ? (
        <p className="text-sm text-ink-soft">Loading packages…</p>
      ) : (
        <Table
          columns={COLUMNS}
          rows={rows}
          rowKey={(pkg) => pkg.package_id}
          caption="Installed workflow packages"
        />
      )}
    </div>
  );
}
