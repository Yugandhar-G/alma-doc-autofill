/**
 * Per-package launch behavior. Labels always come from the manifest (title /
 * description); these constants encode only *how a package is launched*, which
 * genuinely depends on the backend surface it exposes — not on display text.
 *
 *   - self-routed multipart: the package owns its run endpoints under
 *     /api/packages/{id}/runs and starts from document uploads (autofill,
 *     preflight). Its parked run is not a matter-store WorkflowRun.
 *   - link-out: the package keeps a separate legacy workspace (screener).
 *   - matter-path (default): started via POST /api/matters/{id}/runs with a
 *     JSON initial state; mints a WorkflowRun row.
 */
export type LaunchKind = "package_upload" | "link_out" | "matter_state";

const PACKAGE_UPLOAD = new Set(["autofill", "preflight"]);
const LINK_OUT: Record<string, string> = { screener: "/screener" };

export function launchKind(packageId: string): LaunchKind {
  if (PACKAGE_UPLOAD.has(packageId)) return "package_upload";
  if (packageId in LINK_OUT) return "link_out";
  return "matter_state";
}

export function linkOutHref(packageId: string): string | null {
  return LINK_OUT[packageId] ?? null;
}

/** The interrupt kind a self-routed package parks at (drives InterruptPanel). */
export function packageInterruptKind(packageId: string): string {
  if (packageId === "autofill") return "extraction_review";
  if (packageId === "preflight") return "preflight_review";
  return "";
}
