"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { UploadSlot } from "@/components/upload/UploadSlot";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { startPackageRun } from "@/lib/matters/api";
import { packageRunKeys } from "@/lib/matters/queries";
import { validateFile, type FileKind } from "@/lib/fileValidation";

/** One upload slot's local state — file + sniffed kind + hard error. */
type SlotState = { file: File | null; kind: FileKind | null; error: string | null };

const EMPTY_SLOT: SlotState = { file: null, kind: null, error: null };
const ALLOWED: readonly FileKind[] = ["jpeg", "png", "pdf"];

type Props = {
  matterId: string;
  packageId: string;
  /** Preflight collects a case_type; autofill does not. */
  withCaseType: boolean;
  onCancel: () => void;
};

/**
 * Upload collector for the self-routed packages (autofill / preflight). Reuses
 * the existing UploadSlot component and the shared client-side file guardrails,
 * then POSTs the multipart run start. On success it stashes the parked-review
 * payload in the Query cache and navigates to the run view.
 */
export function PackageUploadStarter({ matterId, packageId, withCaseType, onCancel }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [front, setFront] = useState<SlotState>(EMPTY_SLOT);
  const [back, setBack] = useState<SlotState>(EMPTY_SLOT);
  const [g28, setG28] = useState<SlotState>(EMPTY_SLOT);
  const [caseType, setCaseType] = useState("g28_filing");
  const [error, setError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  const select = (set: (s: SlotState) => void) => async (file: File) => {
    const check = await validateFile(file, ALLOWED);
    if (!check.ok) {
      set({ file, kind: null, error: check.error });
      return;
    }
    set({ file, kind: check.kind, error: null });
  };

  const hasStartable = (front.file && !front.error) || (g28.file && !g28.error);
  const hasHardError = Boolean(front.error || back.error || g28.error);

  const start = async () => {
    setError(null);
    if (!hasStartable) {
      setError("Upload at least a passport front or a G-28 to start.");
      return;
    }
    setIsStarting(true);
    try {
      const data = await startPackageRun(
        packageId,
        {
          passportFront: front.error ? null : front.file,
          passportBack: back.error ? null : back.file,
          g28: g28.error ? null : g28.file,
        },
        withCaseType ? caseType : undefined,
      );
      const runId = typeof data.run_id === "string" ? data.run_id : null;
      if (runId === null) {
        setError("The run started but returned no id. Check the backend logs.");
        return;
      }
      // Carry the parked-review payload to the run view via the Query cache.
      queryClient.setQueryData(packageRunKeys.startPayload(runId), data);
      router.push(`/matters/${matterId}/runs/${runId}?pkg=${packageId}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the run.");
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-3">
        <UploadSlot
          slotNumber="1"
          title="Passport (front)"
          badge="Recommended"
          description="The machine-readable data page. JPEG, PNG, or PDF."
          file={front.file}
          kind={front.kind}
          error={front.error}
          isDisabled={isStarting}
          onSelect={select(setFront)}
          onClear={() => setFront(EMPTY_SLOT)}
        />
        <UploadSlot
          slotNumber="2"
          title="Passport (back)"
          badge="Optional"
          description="Fills any fields the front leaves blank."
          file={back.file}
          kind={back.kind}
          error={back.error}
          isDisabled={isStarting}
          onSelect={select(setBack)}
          onClear={() => setBack(EMPTY_SLOT)}
        />
        <UploadSlot
          slotNumber="3"
          title="Form G-28"
          badge="Optional"
          description="Attorney, eligibility, and beneficiary parts."
          file={g28.file}
          kind={g28.kind}
          error={g28.error}
          isDisabled={isStarting}
          onSelect={select(setG28)}
          onClear={() => setG28(EMPTY_SLOT)}
        />
      </div>

      {withCaseType && (
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          <span className="font-medium text-ink-soft">Case type</span>
          <select
            value={caseType}
            onChange={(e) => setCaseType(e.target.value)}
            disabled={isStarting}
            className="rounded-md border border-line bg-surface px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          >
            <option value="g28_filing">G-28 filing</option>
          </select>
        </label>
      )}

      {error && <Banner tone="danger">{error}</Banner>}

      <div className="flex items-center gap-2 border-t border-line pt-4">
        <Button onClick={start} isBusy={isStarting} disabled={!hasStartable || hasHardError}>
          Start workflow
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={isStarting}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
