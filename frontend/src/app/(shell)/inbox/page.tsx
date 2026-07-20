"use client";

import Link from "next/link";

import { Banner } from "@/components/ui/Banner";
import { Chip } from "@/components/ui/Chip";
import { EmptyState } from "@/components/ui/EmptyState";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/matters/format";
import { runHref } from "@/lib/nav";
import { useInbox, useRun } from "@/lib/matters/queries";
import type { Interrupt } from "@/lib/matters/types";

const KIND_LABELS: Record<string, string> = {
  extraction_review: "Extraction review",
  preflight_review: "Pre-flight findings",
  matrix_review: "Evidence matrix review",
};

/**
 * One pending interrupt. The Interrupt payload carries no matter_id, so the
 * link target is resolved by loading the run (which does) — the same run query
 * the destination page reuses from cache.
 */
function InboxRow({ interrupt }: { interrupt: Interrupt }) {
  const run = useRun(interrupt.run_id);
  const matterId = run.data?.run.matter_id ?? null;
  const label = KIND_LABELS[interrupt.kind] ?? interrupt.kind;

  const body = (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone="warn" withDot>
            {label}
          </Chip>
          <span className="font-mono text-xs text-ink-faint">node: {interrupt.node}</span>
        </div>
        <p className="mt-1 text-xs text-ink-faint">Raised {formatDateTime(interrupt.created_at)}</p>
      </div>
      <span aria-hidden className="shrink-0 text-lg text-ink-faint">
        →
      </span>
    </div>
  );

  if (matterId === null) {
    return <li className="opacity-60">{body}</li>;
  }
  return (
    <li>
      <Link
        href={runHref(matterId, interrupt.run_id)}
        className="block transition-colors hover:bg-accent-wash/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        {body}
      </Link>
    </li>
  );
}

export default function InboxPage() {
  const inbox = useInbox();
  const interrupts = inbox.data?.interrupts ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="font-display text-3xl tracking-tight">Inbox</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Every run across the firm waiting on a human decision.
        </p>
      </header>

      {inbox.isError && (
        <Banner tone="danger">
          {inbox.error instanceof ApiError ? inbox.error.message : "Could not load the inbox."}
        </Banner>
      )}

      {inbox.isLoading ? (
        <p className="text-sm text-ink-soft">Loading inbox…</p>
      ) : interrupts.length === 0 ? (
        <EmptyState
          title="Nothing needs review"
          description="When a workflow parks for an attorney or staff decision, it shows up here."
        />
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {interrupts.map((interrupt) => (
            <InboxRow key={interrupt.id} interrupt={interrupt} />
          ))}
        </ul>
      )}
    </div>
  );
}
