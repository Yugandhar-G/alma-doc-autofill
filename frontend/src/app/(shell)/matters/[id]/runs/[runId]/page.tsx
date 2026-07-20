import { Suspense } from "react";

import { RunRouter } from "@/components/runs/RunRouter";

/**
 * Dynamic run route (web/dev). Delegates to the shared RunRouter, the same
 * component the desktop static twin (`/run?...`) renders. See the sibling
 * matter route for why the desktop build emits a single inert sentinel while
 * web/dev returns `[]` (ids resolve on demand). No `[id]`/`[runId]` folder ends
 * up in `out/`.
 */
export function generateStaticParams() {
  if (process.env.NEXT_PUBLIC_DESKTOP === "1") {
    return [{ id: "_", runId: "_" }];
  }
  return [];
}

export default async function RunPage({
  params,
}: {
  params: Promise<{ id: string; runId: string }>;
}) {
  const { id, runId } = await params;
  return (
    <Suspense fallback={<p className="text-sm text-ink-soft">Loading run…</p>}>
      <RunRouter matterId={id} runId={runId} />
    </Suspense>
  );
}
