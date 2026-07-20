"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { useCreateMatter } from "@/lib/matters/queries";
import { matterHref } from "@/lib/nav";
import type { PackageManifestSummary } from "@/lib/matters/types";

type Props = {
  /** Package manifests, used to suggest known matter types via a datalist. */
  packages: PackageManifestSummary[];
};

/** Distinct matter types across all installed packages, for the type datalist. */
function knownMatterTypes(packages: PackageManifestSummary[]): string[] {
  const seen = new Set<string>();
  for (const pkg of packages) for (const type of pkg.matter_types) seen.add(type);
  return [...seen].sort();
}

export function NewMatterForm({ packages }: Props) {
  const router = useRouter();
  const create = useCreateMatter();
  const typeListId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [matterType, setMatterType] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const types = knownMatterTypes(packages);

  const reset = () => {
    setMatterType("");
    setTitle("");
    setError(null);
  };

  const handleSubmit = async () => {
    setError(null);
    const trimmedType = matterType.trim();
    const trimmedTitle = title.trim();
    if (!trimmedType || !trimmedTitle) {
      setError("Both a matter type and a title are required.");
      return;
    }
    try {
      const matter = await create.mutateAsync({
        matter_type: trimmedType,
        title: trimmedTitle,
      });
      reset();
      setIsOpen(false);
      router.push(matterHref(matter.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the matter.");
    }
  };

  if (!isOpen) {
    return (
      <Button variant="primary" onClick={() => setIsOpen(true)}>
        New matter
      </Button>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void handleSubmit();
      }}
      className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink-soft">Matter type</span>
          <input
            list={typeListId}
            value={matterType}
            onChange={(e) => setMatterType(e.target.value)}
            placeholder="e.g. immigration"
            className="rounded-md border border-line bg-surface px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
          <datalist id={typeListId}>
            {types.map((type) => (
              <option key={type} value={type} />
            ))}
          </datalist>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink-soft">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Client matter title"
            className="rounded-md border border-line bg-surface px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
        </label>
      </div>

      {error && (
        <div className="mt-4">
          <Banner tone="danger">{error}</Banner>
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        <Button type="submit" variant="primary" isBusy={create.isPending}>
          Create matter
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={create.isPending}
          onClick={() => {
            reset();
            setIsOpen(false);
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
