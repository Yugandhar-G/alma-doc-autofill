/**
 * Matter-workspace API client. Reuses the shared request/parseEnvelope idioms
 * from lib/api.ts (the {success, data, error} envelope, ApiError surfacing,
 * X-Session-Id header). Two run families live here:
 *
 *   - Matter-path runs (WorkflowService): POST /api/matters/{id}/runs takes a
 *     JSON initial state and mints a WorkflowRun row. Status via /api/runs/{id};
 *     resume via /api/runs/{id}/resume. Suits state-only packages.
 *   - Package-endpoint runs (autofill/preflight own routers): multipart POST to
 *     /api/packages/{pid}/runs. These run standalone graph threads and do NOT
 *     appear in the matter store. Status/resume go through the package router.
 */
import { parseEnvelope, request } from "@/lib/api";
import type { G28Data, PassportData } from "@/lib/types";

import type {
  DocumentUploadData,
  InboxData,
  Matter,
  MatterDetailData,
  MatterListData,
  PackageListData,
  PackageRunStatusData,
  PreflightFinding,
  ResumeRunData,
  RunStatusData,
  WorkflowRun,
} from "./types";

// --- Matters ----------------------------------------------------------------

export async function listMatters(): Promise<MatterListData> {
  const res = await request("/api/matters", { method: "GET" });
  return parseEnvelope<MatterListData>(res);
}

export async function createMatter(input: {
  matter_type: string;
  title: string;
  client_ref?: string | null;
}): Promise<Matter> {
  const res = await request("/api/matters", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = await parseEnvelope<{ matter: Matter }>(res);
  return data.matter;
}

export async function getMatter(matterId: string): Promise<MatterDetailData> {
  const res = await request(`/api/matters/${matterId}`, { method: "GET" });
  return parseEnvelope<MatterDetailData>(res);
}

export async function uploadMatterDocuments(
  matterId: string,
  files: File[],
  docType = "document",
): Promise<DocumentUploadData> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("doc_type", docType);
  const res = await request(`/api/matters/${matterId}/documents`, {
    method: "POST",
    body: form,
  });
  return parseEnvelope<DocumentUploadData>(res);
}

// --- Matter-path runs (state-only packages) ---------------------------------

export async function startMatterRun(
  matterId: string,
  packageId: string,
  initial: Record<string, unknown> = {},
): Promise<WorkflowRun> {
  const res = await request(`/api/matters/${matterId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ package_id: packageId, initial }),
  });
  const data = await parseEnvelope<{ run: WorkflowRun }>(res);
  return data.run;
}

export async function getRun(runId: string): Promise<RunStatusData> {
  const res = await request(`/api/runs/${runId}`, { method: "GET" });
  return parseEnvelope<RunStatusData>(res);
}

export async function resumeRun(
  runId: string,
  payload: Record<string, unknown>,
): Promise<ResumeRunData> {
  const res = await request(`/api/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload }),
  });
  return parseEnvelope<ResumeRunData>(res);
}

// --- Inbox & packages -------------------------------------------------------

export async function getInbox(): Promise<InboxData> {
  const res = await request("/api/inbox", { method: "GET" });
  return parseEnvelope<InboxData>(res);
}

export async function listPackages(): Promise<PackageListData> {
  const res = await request("/api/packages", { method: "GET" });
  return parseEnvelope<PackageListData>(res);
}

// --- Package-endpoint runs (autofill / preflight) ---------------------------

/**
 * Start an autofill or preflight run through the package's own multipart
 * endpoint. The raw envelope `data` is returned untyped-per-slot: it carries
 * `run_id` plus the extraction slots (autofill) or a draft `report`
 * (preflight). Callers narrow it via the panel-specific helpers.
 */
export async function startPackageRun(
  packageId: string,
  files: { passportFront: File | null; passportBack: File | null; g28: File | null },
  caseType?: string,
): Promise<Record<string, unknown>> {
  const form = new FormData();
  if (files.passportFront) form.append("passport_front", files.passportFront);
  if (files.passportBack) form.append("passport_back", files.passportBack);
  if (files.g28) form.append("g28", files.g28);
  if (caseType) form.append("case_type", caseType);
  const res = await request(`/api/packages/${packageId}/runs`, {
    method: "POST",
    body: form,
  });
  return parseEnvelope<Record<string, unknown>>(res);
}

export async function getPackageRun(
  packageId: string,
  runId: string,
): Promise<PackageRunStatusData> {
  const res = await request(`/api/packages/${packageId}/runs/${runId}`, {
    method: "GET",
  });
  return parseEnvelope<PackageRunStatusData>(res);
}

/** Resume an autofill run with the human-reviewed passport/G-28 data. */
export async function resumeAutofillRun(
  runId: string,
  payload: { passport: PassportData | null; g28: G28Data | null; headed?: boolean | null },
): Promise<Record<string, unknown>> {
  const res = await request(`/api/packages/autofill/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseEnvelope<Record<string, unknown>>(res);
}

/**
 * Resume a preflight run with the approved findings. `findings: null` approves
 * the draft unchanged; a list re-validates through the PreflightFinding schema.
 */
export async function resumePreflightRun(
  runId: string,
  findings: PreflightFinding[] | null,
): Promise<Record<string, unknown>> {
  const res = await request(`/api/packages/preflight/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ findings }),
  });
  return parseEnvelope<Record<string, unknown>>(res);
}
