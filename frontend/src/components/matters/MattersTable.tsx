"use client";

import { useRouter } from "next/navigation";

import { Chip, runStatusChip } from "@/components/ui/Chip";
import { formatDate } from "@/lib/matters/format";
import { useMatter } from "@/lib/matters/queries";
import type { Matter, RunStatus, WorkflowRun } from "@/lib/matters/types";

const RUN_STATUS_ORDER: RunStatus[] = [
  "awaiting_input",
  "running",
  "queued",
  "error",
  "done",
];

/** Group a matter's runs by status into ordered {status, count} buckets. */
function summarizeRuns(runs: WorkflowRun[]): { status: RunStatus; count: number }[] {
  const counts = new Map<RunStatus, number>();
  for (const run of runs) counts.set(run.status, (counts.get(run.status) ?? 0) + 1);
  return RUN_STATUS_ORDER.filter((status) => counts.has(status)).map((status) => ({
    status,
    count: counts.get(status) ?? 0,
  }));
}

/**
 * One matter row. Pulls the matter detail to surface its runs' status chips —
 * the list endpoint returns matters only, so runs come from the per-matter
 * detail query (cached, and reused when the row is clicked through to detail).
 */
function MatterRow({ matter }: { matter: Matter }) {
  const router = useRouter();
  const detail = useMatter(matter.id);
  const runs = detail.data?.runs ?? [];
  const summary = summarizeRuns(runs);
  const go = () => router.push(`/matters/${matter.id}`);

  return (
    <tr
      onClick={go}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      }}
      className="cursor-pointer transition-colors hover:bg-accent-wash/40 focus-visible:bg-accent-wash/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
    >
      <td className="px-5 py-3.5 align-middle">
        <span className="font-display text-base text-ink">{matter.title}</span>
        {matter.client_ref && (
          <span className="block text-xs text-ink-faint">{matter.client_ref}</span>
        )}
      </td>
      <td className="px-5 py-3.5 align-middle">
        <Chip tone="neutral">{matter.matter_type}</Chip>
      </td>
      <td className="px-5 py-3.5 align-middle">
        {detail.isLoading ? (
          <span className="text-xs text-ink-faint">Loading runs…</span>
        ) : summary.length === 0 ? (
          <span className="text-xs text-ink-faint">No runs yet</span>
        ) : (
          <span className="flex flex-wrap gap-1.5">
            {summary.map(({ status, count }) => {
              const { tone, label } = runStatusChip(status);
              return (
                <Chip key={status} tone={tone} withDot>
                  {count > 1 ? `${label} ×${count}` : label}
                </Chip>
              );
            })}
          </span>
        )}
      </td>
      <td className="px-5 py-3.5 align-middle text-sm text-ink-soft">
        {formatDate(matter.created_at)}
      </td>
    </tr>
  );
}

export function MattersTable({ matters }: { matters: Matter[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-line bg-paper/50">
            {["Matter", "Type", "Runs", "Opened"].map((header) => (
              <th
                key={header}
                scope="col"
                className="px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-soft"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {matters.map((matter) => (
            <MatterRow key={matter.id} matter={matter} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
