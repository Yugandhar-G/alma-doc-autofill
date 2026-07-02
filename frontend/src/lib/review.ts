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

/** Index envelope warnings by their field path for inline display. */
export function warningsByField(env: ExtractionEnvelope | null): Record<string, string> {
  if (!env) return {};
  const map: Record<string, string> = {};
  for (const w of env.warnings) {
    map[w.field] = w.message;
  }
  return map;
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
