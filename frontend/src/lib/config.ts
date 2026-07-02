/**
 * Single source of configuration. Nothing else in the app may hardcode the
 * backend origin or upload limits — import from here.
 */

/** FastAPI backend origin. Override with NEXT_PUBLIC_API_URL. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Upload size cap — mirrors the backend guardrail. */
export const MAX_FILE_MB = 10;
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

/** File-picker accept attribute for both upload slots. */
export const FILE_ACCEPT =
  ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

/** The live form the backend fills — shown for context, never fetched here. */
export const HUMAN_NOTE =
  "The form is filled in a browser window on the machine running the backend. " +
  "Nothing is submitted or signed.";
