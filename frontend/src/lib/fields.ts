/**
 * Field descriptors that drive the editable review tables. Keys must match
 * the Pydantic schema attribute names exactly — these travel back to the
 * backend on populate and re-validate through the same schemas.
 */
import type { AttorneyInfo, BeneficiaryInfo, EligibilityInfo, PassportData } from "./types";

export type InputKind = "text" | "date" | "sex" | "bool" | "unit";

export interface FieldDef<K extends string = string> {
  key: K;
  label: string;
  kind: InputKind;
  hint?: string;
}

export const PASSPORT_FIELDS: FieldDef<keyof PassportData>[] = [
  { key: "surname", label: "Surname", kind: "text" },
  { key: "given_names", label: "Given names", kind: "text" },
  { key: "middle_names", label: "Middle names", kind: "text" },
  { key: "passport_number", label: "Passport number", kind: "text" },
  { key: "country_of_issue", label: "Country of issue", kind: "text", hint: "Full country name" },
  { key: "nationality", label: "Nationality", kind: "text", hint: "Full country name" },
  { key: "date_of_birth", label: "Date of birth", kind: "date" },
  { key: "place_of_birth", label: "Place of birth", kind: "text" },
  { key: "sex", label: "Sex", kind: "sex" },
  { key: "date_of_issue", label: "Date of issue", kind: "date" },
  { key: "date_of_expiration", label: "Date of expiration", kind: "date" },
];

export const ATTORNEY_FIELDS: FieldDef<keyof AttorneyInfo>[] = [
  { key: "online_account_number", label: "USCIS online account number", kind: "text" },
  { key: "family_name", label: "Family name", kind: "text" },
  { key: "given_name", label: "Given name", kind: "text" },
  { key: "middle_name", label: "Middle name", kind: "text" },
  { key: "street_number_and_name", label: "Street number and name", kind: "text" },
  { key: "apt_ste_flr", label: "Apt / Ste / Flr", kind: "unit" },
  { key: "apt_ste_flr_number", label: "Unit number", kind: "text" },
  { key: "city", label: "City or town", kind: "text" },
  { key: "state", label: "State", kind: "text", hint: "Full state name, e.g. California" },
  { key: "zip_code", label: "ZIP code", kind: "text" },
  { key: "country", label: "Country", kind: "text", hint: "Full country name" },
  { key: "daytime_phone", label: "Daytime telephone", kind: "text" },
  { key: "mobile_phone", label: "Mobile telephone", kind: "text" },
  { key: "email", label: "Email address", kind: "text" },
];

export const ELIGIBILITY_FIELDS: FieldDef<keyof EligibilityInfo>[] = [
  { key: "is_attorney", label: "1.a — I am an attorney", kind: "bool" },
  { key: "licensing_authority", label: "1.b — Licensing authority", kind: "text" },
  { key: "bar_number", label: "1.b — Bar number", kind: "text" },
  {
    key: "subject_to_discipline",
    label: "1.c — Subject to disciplinary orders",
    kind: "bool",
    hint: "Yes = am subject, No = am not subject",
  },
  { key: "law_firm", label: "1.d — Law firm or organization", kind: "text" },
  { key: "is_accredited_representative", label: "2.a — Accredited representative", kind: "bool" },
  { key: "recognized_organization", label: "2.b — Recognized organization", kind: "text" },
  { key: "accreditation_date", label: "2.c — Accreditation date", kind: "date" },
  { key: "is_associated", label: "3 — Associated with prior representative", kind: "bool" },
  { key: "associated_with_name", label: "3 — Associated with (name)", kind: "text" },
  { key: "is_law_student", label: "4.a — Law student or graduate", kind: "bool" },
  { key: "law_student_name", label: "4.b — Student name", kind: "text" },
];

export const BENEFICIARY_FIELDS: FieldDef<keyof BeneficiaryInfo>[] = [
  { key: "family_name", label: "Family name", kind: "text" },
  { key: "given_name", label: "Given name", kind: "text" },
  { key: "middle_name", label: "Middle name", kind: "text" },
];
