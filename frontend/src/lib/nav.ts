/**
 * Internal navigation href builder. The two matter/run detail screens have
 * dynamic segments (`/matters/[id]`, `/matters/[id]/runs/[runId]`) that cannot
 * be statically exported for the desktop build, so under the desktop flag we
 * route through static query-param twin routes (`/matter?id=`, `/run?...`)
 * that render the exact same client components.
 *
 * Every internal link or router.push to those two screens MUST go through
 * these helpers — never hardcode the path — so the same source builds correctly
 * for both web (path-style) and desktop (query-style).
 *
 * The flag is a build-time constant (`NEXT_PUBLIC_DESKTOP=1` set by
 * `build:desktop`), so the correct branch is inlined per build with no runtime
 * branching in the shipped bundle.
 */
const IS_DESKTOP = process.env.NEXT_PUBLIC_DESKTOP === "1";

/** Link to a matter detail screen. */
export function matterHref(matterId: string): string {
  if (IS_DESKTOP) {
    return `/matter?id=${encodeURIComponent(matterId)}`;
  }
  return `/matters/${matterId}`;
}

/**
 * Link to a workflow run screen. `pkg` marks a self-routed package run
 * (autofill/preflight) whose status/resume go through the package router; it is
 * carried as a query param on both web and desktop so the run screen reads it
 * from `useSearchParams` uniformly.
 */
export function runHref(
  matterId: string,
  runId: string,
  pkg?: string | null,
): string {
  if (IS_DESKTOP) {
    const params = new URLSearchParams({ matterId, runId });
    if (pkg) params.set("pkg", pkg);
    return `/run?${params.toString()}`;
  }
  const query = pkg ? `?pkg=${encodeURIComponent(pkg)}` : "";
  return `/matters/${matterId}/runs/${runId}${query}`;
}
