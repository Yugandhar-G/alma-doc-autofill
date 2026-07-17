/**
 * Thin client for the FastAPI backend. Every endpoint returns the shared
 * {success, data, error} envelope; failures surface as ApiError with a
 * user-facing message, never as silently-empty data.
 */
import { API_BASE } from "./config";
import { getSessionId } from "./telemetry";
import type {
  ApiResponse,
  ExtractionEnvelope,
  ExtractionResult,
  G28Data,
  HealthInfo,
  PassportData,
  PopulationReport,
  SlotResult,
} from "./types";

export class ApiError extends Error {}

export async function parseEnvelope<T>(res: Response): Promise<T> {
  let body: ApiResponse<T>;
  try {
    body = (await res.json()) as ApiResponse<T>;
  } catch {
    throw new ApiError(
      `The backend returned an unreadable response (HTTP ${res.status}). Is it running on ${API_BASE}?`,
    );
  }
  if (!body.success || body.data == null) {
    throw new ApiError(body.error ?? "The backend reported an unknown error.");
  }
  return body.data;
}

export async function request(path: string, init: RequestInit): Promise<Response> {
  // The session id groups this tab's requests into one observability session.
  const headers = {
    ...(init.headers as Record<string, string> | undefined),
    "X-Session-Id": getSessionId(),
  };
  try {
    return await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      `Could not reach the backend at ${API_BASE}. Start it with \`make dev\` and try again.`,
    );
  }
}

export async function fetchHealth(): Promise<HealthInfo> {
  const res = await request("/api/health", { method: "GET" });
  return parseEnvelope<HealthInfo>(res);
}

function toSlotResult(slot: Record<string, unknown> | undefined | null): SlotResult | null {
  if (slot === undefined || slot === null) return null;
  // Per-file guardrail rejections come back as {error} instead of an envelope.
  if (typeof slot.error === "string") {
    return { kind: "rejected", error: slot.error };
  }
  return { kind: "ok", envelope: slot as unknown as ExtractionEnvelope };
}

/**
 * Send whichever documents were uploaded in a single multipart request.
 * The backend merges passport front + back server-side (front authoritative,
 * back fills nulls) and returns one `passport` envelope; a rejected back side
 * arrives separately as `passport_back: {error}` without sinking the front.
 */
export async function extractDocuments(files: {
  passportFront: File | null;
  passportBack: File | null;
  g28: File | null;
}): Promise<ExtractionResult> {
  const form = new FormData();
  if (files.passportFront) form.append("passport_front", files.passportFront);
  if (files.passportBack) form.append("passport_back", files.passportBack);
  if (files.g28) form.append("g28", files.g28);

  const res = await request("/api/extract", { method: "POST", body: form });
  const data = await parseEnvelope<Record<string, Record<string, unknown>>>(res);

  const backSlot = toSlotResult(data.passport_back);
  const result: ExtractionResult = {
    passport: toSlotResult(data.passport),
    passportBackError: backSlot?.kind === "rejected" ? backSlot.error : null,
    g28: toSlotResult(data.g28),
  };
  if (files.passportFront && result.passport === null) {
    throw new ApiError("The backend response was missing the passport extraction result.");
  }
  if (files.g28 && result.g28 === null) {
    throw new ApiError("The backend response was missing the G-28 extraction result.");
  }
  return result;
}

export async function populateForm(
  passport: PassportData | null,
  g28: G28Data | null,
): Promise<PopulationReport> {
  const res = await request("/api/populate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ passport, g28 }),
  });
  return parseEnvelope<PopulationReport>(res);
}
