/**
 * TypeScript mirrors of backend/app/schemas/*.py — the Pydantic models are
 * the source of truth. Every extraction field is nullable: a null means
 * "not found on the document", never an error.
 */

export interface PassportData {
  surname: string | null;
  given_names: string | null;
  middle_names: string | null;
  passport_number: string | null;
  country_of_issue: string | null;
  nationality: string | null;
  date_of_birth: string | null;
  place_of_birth: string | null;
  sex: string | null;
  date_of_issue: string | null;
  date_of_expiration: string | null;
}

export const EMPTY_PASSPORT: PassportData = {
  surname: null,
  given_names: null,
  middle_names: null,
  passport_number: null,
  country_of_issue: null,
  nationality: null,
  date_of_birth: null,
  place_of_birth: null,
  sex: null,
  date_of_issue: null,
  date_of_expiration: null,
};

export type AptSteFlr = "apt" | "ste" | "flr";

export interface AttorneyInfo {
  online_account_number: string | null;
  family_name: string | null;
  given_name: string | null;
  middle_name: string | null;
  street_number_and_name: string | null;
  apt_ste_flr: AptSteFlr | null;
  apt_ste_flr_number: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  country: string | null;
  daytime_phone: string | null;
  mobile_phone: string | null;
  email: string | null;
}

export interface EligibilityInfo {
  is_attorney: boolean | null;
  licensing_authority: string | null;
  bar_number: string | null;
  subject_to_discipline: boolean | null;
  law_firm: string | null;
  is_accredited_representative: boolean | null;
  recognized_organization: string | null;
  accreditation_date: string | null;
  is_associated: boolean | null;
  associated_with_name: string | null;
  is_law_student: boolean | null;
  law_student_name: string | null;
}

export interface BeneficiaryInfo {
  family_name: string | null;
  given_name: string | null;
  middle_name: string | null;
}

export interface G28Data {
  attorney: AttorneyInfo;
  eligibility: EligibilityInfo;
  beneficiary: BeneficiaryInfo;
}

export const EMPTY_G28: G28Data = {
  attorney: {
    online_account_number: null,
    family_name: null,
    given_name: null,
    middle_name: null,
    street_number_and_name: null,
    apt_ste_flr: null,
    apt_ste_flr_number: null,
    city: null,
    state: null,
    zip_code: null,
    country: null,
    daytime_phone: null,
    mobile_phone: null,
    email: null,
  },
  eligibility: {
    is_attorney: null,
    licensing_authority: null,
    bar_number: null,
    subject_to_discipline: null,
    law_firm: null,
    is_accredited_representative: null,
    recognized_organization: null,
    accreditation_date: null,
    is_associated: null,
    associated_with_name: null,
    is_law_student: null,
    law_student_name: null,
  },
  beneficiary: {
    family_name: null,
    given_name: null,
    middle_name: null,
  },
};

export type DocType = "passport" | "g28";
export type DetectedType = "passport" | "g28" | "other" | "unknown";

export interface FieldWarning {
  field: string;
  message: string;
}

export interface ExtractionEnvelope {
  document_type_requested: DocType;
  document_type_detected: DetectedType;
  data: Record<string, unknown> | null;
  warnings: FieldWarning[];
  model_used: string | null;
  source_hash: string | null;
}

export interface PopulationEntry {
  selector: string;
  source: string;
  action: "fill" | "select_label" | "select_value" | "check";
  status: "filled" | "skipped_null" | "mismatch" | "error";
  expected: string | null;
  actual: string | null;
}

export interface PopulationReport {
  target_url: string;
  entries: PopulationEntry[];
  filled: number;
  skipped_null: number;
  mismatches: number;
  errors: number;
  ok: boolean;
  /** Content hash of the captured filled-form artifact; null when capture failed. */
  artifact_id: string | null;
  artifact_kind: "pdf" | "png" | null;
}

export interface ApiResponse<T = Record<string, unknown>> {
  success: boolean;
  data: T | null;
  error: string | null;
}

export interface HealthInfo {
  storage: "supabase" | "local";
  model: string;
  gemini_key_present: boolean;
}

/**
 * Outcome for one upload slot of an /api/extract call. A guardrail rejection
 * (size, page cap, blur gate) comes back as {error} instead of an envelope.
 */
export type SlotResult =
  | { kind: "ok"; envelope: ExtractionEnvelope }
  | { kind: "rejected"; error: string };

export interface ExtractionResult {
  /** Merged passport envelope (front authoritative, back fills nulls) or the front's guardrail rejection. */
  passport: SlotResult | null;
  /** Set only when the back side itself was rejected; the front's envelope still arrives in `passport`. */
  passportBackError: string | null;
  g28: SlotResult | null;
}

/** Count fields that carry a value (non-null, non-empty). */
export function countFilled(record: Record<string, unknown>): number {
  return Object.values(record).filter((v) => v !== null && v !== "").length;
}
