"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { PackageUploadStarter } from "@/components/matters/PackageUploadStarter";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { launchKind, linkOutHref } from "@/lib/matters/packages";
import { useStartMatterRun } from "@/lib/matters/queries";
import type { Matter, PackageManifestSummary } from "@/lib/matters/types";

type Props = {
  matter: Matter;
  packages: PackageManifestSummary[];
};

/** Packages whose matter_types include this matter's type. */
function applicablePackages(
  packages: PackageManifestSummary[],
  matterType: string,
): PackageManifestSummary[] {
  return packages.filter((pkg) => pkg.matter_types.includes(matterType));
}

export function StartWorkflow({ matter, packages }: Props) {
  const router = useRouter();
  const startMatterRun = useStartMatterRun(matter.id);
  const [selected, setSelected] = useState<PackageManifestSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const options = applicablePackages(packages, matter.matter_type);

  const startStatePackage = async (pkg: PackageManifestSummary) => {
    setError(null);
    try {
      const run = await startMatterRun.mutateAsync({ packageId: pkg.package_id });
      router.push(`/matters/${matter.id}/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the workflow.");
    }
  };

  if (options.length === 0) {
    return (
      <Banner tone="info">
        No installed workflow package targets “{matter.matter_type}” matters.
      </Banner>
    );
  }

  // Step 2: a self-routed package was picked → collect its uploads inline.
  if (selected !== null && launchKind(selected.package_id) === "package_upload") {
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
        <div>
          <h3 className="font-display text-lg">{selected.title}</h3>
          <p className="text-sm text-ink-soft">{selected.description}</p>
        </div>
        <PackageUploadStarter
          matterId={matter.id}
          packageId={selected.package_id}
          withCaseType={selected.package_id === "preflight"}
          onCancel={() => setSelected(null)}
        />
      </div>
    );
  }

  // Step 1: the package picker.
  return (
    <div className="flex flex-col gap-3">
      {error && <Banner tone="danger">{error}</Banner>}
      <div className="grid gap-3 sm:grid-cols-2">
        {options.map((pkg) => {
          const kind = launchKind(pkg.package_id);
          const href = linkOutHref(pkg.package_id);
          return (
            <div
              key={pkg.package_id}
              className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]"
            >
              <div>
                <h3 className="font-display text-lg">{pkg.title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-ink-soft">{pkg.description}</p>
              </div>
              <div className="mt-auto">
                {kind === "link_out" && href ? (
                  <Link href={href}>
                    <Button variant="secondary">Open {pkg.title}</Button>
                  </Link>
                ) : kind === "package_upload" ? (
                  <Button variant="primary" onClick={() => setSelected(pkg)}>
                    Start
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    isBusy={startMatterRun.isPending}
                    onClick={() => startStatePackage(pkg)}
                  >
                    Start
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
