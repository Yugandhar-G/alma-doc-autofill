/**
 * Client-side cross-document consistency check: the person named on the
 * passport should match the G-28 beneficiary (Part 3). Case-insensitive,
 * whitespace-tolerant. A disagreement is a warning for the reviewer, never
 * a blocker — documents legitimately differ (married names, transliteration).
 */
import type { G28Data, PassportData } from "./types";

export interface NameConflict {
  label: string;
  passportValue: string;
  g28Value: string;
}

function normalize(value: string | null): string | null {
  if (value === null) return null;
  const collapsed = value.trim().replace(/\s+/g, " ").toLowerCase();
  return collapsed === "" ? null : collapsed;
}

export function nameConflicts(
  passport: PassportData | null,
  g28: G28Data | null,
): NameConflict[] {
  if (!passport || !g28) return [];
  const conflicts: NameConflict[] = [];

  const surname = normalize(passport.surname);
  const familyName = normalize(g28.beneficiary.family_name);
  if (surname !== null && familyName !== null && surname !== familyName) {
    conflicts.push({
      label: "Family name",
      passportValue: passport.surname ?? "",
      g28Value: g28.beneficiary.family_name ?? "",
    });
  }

  const given = normalize(passport.given_names);
  const beneficiaryGiven = normalize(g28.beneficiary.given_name);
  // Passports often print given + middle names together; accept that too.
  const beneficiaryFull = normalize(
    [g28.beneficiary.given_name, g28.beneficiary.middle_name].filter(Boolean).join(" "),
  );
  if (
    given !== null &&
    beneficiaryGiven !== null &&
    given !== beneficiaryGiven &&
    given !== beneficiaryFull
  ) {
    conflicts.push({
      label: "Given name(s)",
      passportValue: passport.given_names ?? "",
      g28Value: g28.beneficiary.given_name ?? "",
    });
  }

  return conflicts;
}
