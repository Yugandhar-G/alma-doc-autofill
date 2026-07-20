/**
 * Single source of configuration. Nothing else in the app may hardcode the
 * backend origin or upload limits — import from here.
 */

/**
 * Runtime API handshake injected by the Tauri desktop shell before the app
 * scripts run. The shell picks a free port, mints a per-launch bearer token,
 * spawns the sidecar, and injects this object via an init script. On the web
 * it is simply absent and the build-time base is used.
 */
export type RuntimeApi = { base: string; token: string | null };

declare global {
  interface Window {
    __YUNAKI_API__?: { base: string; token?: string | null };
  }
}

/**
 * Build-time backend origin. Override with NEXT_PUBLIC_API_URL. Used only when
 * no runtime handshake is present (i.e. every web deployment).
 */
const BUILD_TIME_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Resolve the live API base + token. The Tauri shell's injected value wins at
 * runtime; on the web the injected object is undefined so this is identical to
 * the build-time base with no token. Read this per-call — never cache it in a
 * module-level const, or the runtime injection is lost.
 */
export function getApiConfig(): RuntimeApi {
  if (typeof window !== "undefined" && window.__YUNAKI_API__?.base) {
    const injected = window.__YUNAKI_API__;
    return { base: injected.base, token: injected.token ?? null };
  }
  return { base: BUILD_TIME_API_BASE, token: null };
}

/** The live backend origin (runtime override when present, build-time otherwise). */
export function getApiBase(): string {
  return getApiConfig().base;
}

/** Upload size cap — mirrors the backend guardrail. */
export const MAX_FILE_MB = 10;
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

/** File-picker accept attribute for all upload slots. */
export const FILE_ACCEPT =
  ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

/**
 * When the merged passport extraction yields this many readable fields or
 * fewer, prompt for a sharper re-upload before letting the user continue.
 */
export const PASSPORT_LOW_FIELD_THRESHOLD = 2;

/** The live form the backend fills — shown for context, never fetched here. */
export const HUMAN_NOTE =
  "The form is filled in a browser window on the machine running the backend. " +
  "Nothing is submitted or signed.";
