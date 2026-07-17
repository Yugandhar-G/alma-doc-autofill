/**
 * Screener client — same conventions as lib/api.ts (shared {success, data,
 * error} envelope, ApiError surfaces, X-Session-Id header) plus a fetch-based
 * SSE reader for the run/review streams. EventSource cannot send the session
 * header, so the streams are read via response.body.getReader() with a small
 * line parser that survives partial frames across chunks.
 */
import { ApiError, parseEnvelope, request } from "@/lib/api";
import type {
  DocumentsUploadResult,
  EvidenceDocRecord,
  EvidenceMatrix,
  EvidenceSlotResult,
  IntakeAnswers,
  ScreenerEvent,
  ScreenerReport,
  VisaType,
} from "./types";

export async function createScreenerSession(): Promise<string> {
  const res = await request("/api/screener/session", { method: "POST" });
  const data = await parseEnvelope<{ session_id: string }>(res);
  return data.session_id;
}

export async function submitIntake(
  sessionId: string,
  visaTargets: VisaType[],
  intake: IntakeAnswers,
): Promise<void> {
  const res = await request(`/api/screener/session/${sessionId}/intake`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visa_targets: visaTargets, intake }),
  });
  if (res.status === 422) {
    throw new ApiError(
      "The intake answers were rejected by the backend — an answer exceeds the length limit.",
    );
  }
  await parseEnvelope<{ session_id: string }>(res);
}

function toSlotResult(slot: unknown): EvidenceSlotResult {
  const record = slot as Record<string, unknown>;
  // Per-slot guardrail rejections come back as {error} instead of a record.
  if (typeof record?.error === "string") {
    return { kind: "rejected", error: record.error };
  }
  return { kind: "ok", record: slot as EvidenceDocRecord };
}

/**
 * Upload the resume and/or evidence documents. Slot isolation is preserved:
 * one rejected file arrives as its own {error} without sinking the others.
 */
export async function uploadScreenerDocuments(
  sessionId: string,
  files: { resume?: File; evidence?: File[] },
): Promise<DocumentsUploadResult> {
  const form = new FormData();
  if (files.resume) form.append("resume", files.resume);
  for (const file of files.evidence ?? []) form.append("evidence", file);

  const res = await request(`/api/screener/session/${sessionId}/documents`, {
    method: "POST",
    body: form,
  });
  const data = await parseEnvelope<{ resume?: unknown; evidence: unknown[] }>(res);
  return {
    resume: data.resume === undefined ? null : toSlotResult(data.resume),
    evidence: (data.evidence ?? []).map(toSlotResult),
  };
}

export async function fetchScreenerReport(sessionId: string): Promise<ScreenerReport> {
  const res = await request(`/api/screener/session/${sessionId}/report`, {
    method: "GET",
  });
  return parseEnvelope<ScreenerReport>(res);
}

/**
 * Read one SSE response ("data: {json}\n\n" frames) and forward each parsed
 * event. Handles multi-line chunks, partial lines across reads, and the JSON
 * error-envelope fallback the backend sends for setup failures.
 */
async function readSseStream(
  res: Response,
  onEvent: (event: ScreenerEvent) => void,
): Promise<void> {
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("text/event-stream")) {
    // Setup errors arrive as the standard JSON envelope, not a stream.
    await parseEnvelope<Record<string, unknown>>(res);
    throw new ApiError("The backend did not start a screening stream.");
  }
  if (res.body === null) {
    throw new ApiError("The backend stream had no readable body.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineAt = buffer.indexOf("\n");
      while (newlineAt !== -1) {
        const line = buffer.slice(0, newlineAt).replace(/\r$/, "");
        buffer = buffer.slice(newlineAt + 1);
        newlineAt = buffer.indexOf("\n");
        if (!line.startsWith("data:")) continue; // blank frame separators
        const raw = line.slice(5).trim();
        if (raw === "") continue;
        let parsed: ScreenerEvent;
        try {
          parsed = JSON.parse(raw) as ScreenerEvent;
        } catch {
          console.warn("screener stream: dropped malformed frame", raw.slice(0, 120));
          continue;
        }
        onEvent(parsed);
      }
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      "The connection to the screening stream dropped mid-run. Retry to resume.",
    );
  } finally {
    reader.releaseLock();
  }
}

/**
 * Start the screening run. Resolves when the stream closes (normally right
 * after `awaiting_review` or `done`); every event is forwarded to onEvent.
 */
export async function streamRun(
  sessionId: string,
  onEvent: (event: ScreenerEvent) => void,
): Promise<void> {
  const res = await request(`/api/screener/session/${sessionId}/run`, {
    method: "POST",
  });
  await readSseStream(res, onEvent);
}

/** Resume the interrupted run with the human-reviewed matrix. */
export async function streamReview(
  sessionId: string,
  matrix: EvidenceMatrix,
  onEvent: (event: ScreenerEvent) => void,
): Promise<void> {
  const res = await request(`/api/screener/session/${sessionId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ matrix }),
  });
  await readSseStream(res, onEvent);
}
