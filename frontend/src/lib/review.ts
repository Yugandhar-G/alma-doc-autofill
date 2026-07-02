/**
 * Helpers that turn raw extraction envelopes into the editable review state.
 * Nulls are preserved end-to-end: a field the extraction could not read stays
 * null until a human types a value.
 */
import {
  EMPTY_G28,
  EMPTY_PASSPORT,
  type ExtractionEnvelope,
  type G28Data,
  type PassportData,
} from "./types";

export function passportFromEnvelope(env: ExtractionEnvelope | null): PassportData {
  if (!env?.data) return { ...EMPTY_PASSPORT };
  return { ...EMPTY_PASSPORT, ...(env.data as Partial<PassportData>) };
}

export function g28FromEnvelope(env: ExtractionEnvelope | null): G28Data {
  const d = (env?.data ?? null) as Partial<G28Data> | null;
  return {
    attorney: { ...EMPTY_G28.attorney, ...(d?.attorney ?? {}) },
    eligibility: { ...EMPTY_G28.eligibility, ...(d?.eligibility ?? {}) },
    beneficiary: { ...EMPTY_G28.beneficiary, ...(d?.beneficiary ?? {}) },
  };
}

/**
 * Envelope-level warnings about the passport back side are prefixed "back:"
 * by the backend (e.g. "back:document_type_detected", "back:merge"). They
 * are not field warnings and are surfaced separately via backWarning().
 */
const BACK_WARNING_PREFIX = "back:";

export type BackWarningKey = "document_type_detected" | "merge";

/** Index field-level envelope warnings by their field path for inline display. */
export function warningsByField(env: ExtractionEnvelope | null): Record<string, string> {
  if (!env) return {};
  const map: Record<string, string> = {};
  for (const w of env.warnings) {
    if (w.field.startsWith(BACK_WARNING_PREFIX)) continue;
    map[w.field] = w.message;
  }
  return map;
}

/** Read a back-side warning ("back:document_type_detected" or "back:merge") off the merged passport envelope. */
export function backWarning(
  env: ExtractionEnvelope | null,
  key: BackWarningKey,
): string | undefined {
  return env?.warnings.find((w) => w.field === `${BACK_WARNING_PREFIX}${key}`)?.message;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  passport: "a passport",
  g28: "a Form G-28",
  other: "a different kind of document",
  unknown: "unrecognizable",
};

/** Human phrasing for a document_type_detected value. */
export function describeDetectedType(detected: string): string {
  return DOC_TYPE_LABELS[detected] ?? detected;
}

/**
 * Look up a warning for a field that may be keyed either as a dotted path
 * ("attorney.city") or as a bare field name ("city").
 */
export function fieldWarning(
  map: Record<string, string>,
  key: string,
  section?: string,
): string | undefined {
  if (section !== undefined) {
    return map[`${section}.${key}`] ?? map[key];
  }
  return map[key];
}
