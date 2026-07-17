/**
 * Frontend telemetry — a per-tab session id that groups all backend traces,
 * plus fire-and-forget UI events relayed via POST /api/telemetry.
 *
 * PII policy: events carry step names, document types, counts, and booleans.
 * Never file names, extracted values, or free-form user input.
 */
import { API_BASE } from "./config";

const SESSION_KEY = "yunaki-session-id";

export function getSessionId(): string {
  if (typeof window === "undefined") return "server";
  const existing = window.sessionStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.sessionStorage.setItem(SESSION_KEY, created);
  return created;
}

export type TelemetryValue = string | number | boolean | null;

/** Send one UI event. Failures are logged and swallowed — telemetry must
 * never affect the user flow. Event names must match the backend's
 * `ui.*` allowlist pattern. */
export function trackEvent(
  name: `ui.${string}`,
  metadata: Record<string, TelemetryValue> = {},
): void {
  if (typeof window === "undefined") return;
  void fetch(`${API_BASE}/api/telemetry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, session_id: getSessionId(), metadata }),
    keepalive: true,
  }).catch((err) => {
    console.warn("telemetry event dropped", name, err);
  });
}
