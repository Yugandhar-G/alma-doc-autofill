"use client";

import { useRef, useState } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/matters/format";
import { useUploadDocuments } from "@/lib/matters/queries";
import type { MatterDocument } from "@/lib/matters/types";

type Props = {
  matterId: string;
  documents: MatterDocument[];
};

export function MatterDocuments({ matterId, documents }: Props) {
  const upload = useUploadDocuments(matterId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<string[]>([]);

  const handleFiles = async (files: FileList | null) => {
    if (files === null || files.length === 0) return;
    setError(null);
    setRejected([]);
    try {
      const result = await upload.mutateAsync([...files]);
      setRejected(result.rejected);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-xl tracking-tight">Documents</h2>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => void handleFiles(e.target.files)}
        />
        <Button
          variant="secondary"
          isBusy={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          Upload documents
        </Button>
      </div>

      {error && <Banner tone="danger">{error}</Banner>}
      {rejected.length > 0 && (
        <Banner tone="warn">
          Rejected (too large or empty): {rejected.join(", ")}. Everything else was saved.
        </Banner>
      )}

      {documents.length === 0 ? (
        <EmptyState
          title="No documents yet"
          description="Upload passports, forms, or evidence for this matter. Workflows can read them when they run."
        />
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {documents.map((doc) => (
            <li key={doc.id} className="flex items-center justify-between gap-4 px-5 py-3.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink" title={doc.filename}>
                  {doc.filename}
                </p>
                <p className="text-xs text-ink-faint">
                  {doc.doc_type} · added {formatDateTime(doc.created_at)}
                </p>
              </div>
              <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                {doc.doc_id.slice(0, 10)}…
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
