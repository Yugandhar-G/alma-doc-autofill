"""Allow-list mapping of target-form controls to schema paths.

This list is the ONLY source of selectors the population plane may touch.
Submit, sign, and Part 4/5 controls are structurally absent — do not add them.

Recon notes (verified against the live form 2026-07-01, snapshot in
tests/data/form_snapshot.html):
- Part 3 First Name(s) and Middle Name(s) BOTH carry id/name
  "passport-given-names" (planted trap) → middle name is addressed
  positionally via `nth`.
- #state option values are 2-letter codes, labels full names → select by label.
- #passport-sex option values are M/F/X → select by value.
- 1.c discipline is two independent checkboxes, not radios.
- All date fields are input[type=date] → fill() needs YYYY-MM-DD.
"""
from dataclasses import dataclass
from typing import Literal

Action = Literal["fill", "select_label", "select_value", "check"]


@dataclass(frozen=True)
class FieldSpec:
    selector: str                 # CSS selector
    source: str                   # dotted path into {"passport": ..., "g28": ...}
    action: Action = "fill"
    nth: int | None = None        # positional disambiguation (duplicate-id trap)
    check_when: bool | None = None  # for "check": only check when source equals this


FIELD_MAP: tuple[FieldSpec, ...] = (
    # ── Part 1 — Attorney ────────────────────────────────────────────────
    FieldSpec("#online-account", "g28.attorney.online_account_number"),
    FieldSpec("#family-name", "g28.attorney.family_name"),
    FieldSpec("#given-name", "g28.attorney.given_name"),
    FieldSpec("#middle-name", "g28.attorney.middle_name"),
    FieldSpec("#street-number", "g28.attorney.street_number_and_name"),
    FieldSpec("#apt", "g28.attorney.apt_ste_flr", action="check", check_when=True),   # value == "apt" resolved in fill.py
    FieldSpec("#ste", "g28.attorney.apt_ste_flr", action="check", check_when=True),
    FieldSpec("#flr", "g28.attorney.apt_ste_flr", action="check", check_when=True),
    FieldSpec("#apt-number", "g28.attorney.apt_ste_flr_number"),
    FieldSpec("#city", "g28.attorney.city"),
    FieldSpec("#state", "g28.attorney.state", action="select_label"),
    FieldSpec("#zip", "g28.attorney.zip_code"),
    FieldSpec("#country", "g28.attorney.country"),
    FieldSpec("#daytime-phone", "g28.attorney.daytime_phone"),
    FieldSpec("#mobile-phone", "g28.attorney.mobile_phone"),
    FieldSpec("#email", "g28.attorney.email"),
    # ── Part 2 — Eligibility ─────────────────────────────────────────────
    FieldSpec("#attorney-eligible", "g28.eligibility.is_attorney", action="check", check_when=True),
    FieldSpec("#licensing-authority", "g28.eligibility.licensing_authority"),
    FieldSpec("#bar-number", "g28.eligibility.bar_number"),
    FieldSpec("#not-subject", "g28.eligibility.subject_to_discipline", action="check", check_when=False),
    FieldSpec("#am-subject", "g28.eligibility.subject_to_discipline", action="check", check_when=True),
    FieldSpec("#law-firm", "g28.eligibility.law_firm"),
    FieldSpec("#accredited-rep", "g28.eligibility.is_accredited_representative", action="check", check_when=True),
    FieldSpec("#recognized-org", "g28.eligibility.recognized_organization"),
    FieldSpec("#accreditation-date", "g28.eligibility.accreditation_date"),
    FieldSpec("#associated-with", "g28.eligibility.is_associated", action="check", check_when=True),
    FieldSpec("#associated-with-name", "g28.eligibility.associated_with_name"),
    FieldSpec("#law-student", "g28.eligibility.is_law_student", action="check", check_when=True),
    FieldSpec("#student-name", "g28.eligibility.law_student_name"),
    # ── Part 3 — Passport / Beneficiary ──────────────────────────────────
    FieldSpec("#passport-surname", "passport.surname"),
    FieldSpec('input[name="passport-given-names"]', "passport.given_names", nth=0),
    FieldSpec('input[name="passport-given-names"]', "passport.middle_names", nth=1),  # duplicate-id trap
    FieldSpec("#passport-number", "passport.passport_number"),
    FieldSpec("#passport-country", "passport.country_of_issue"),
    FieldSpec("#passport-nationality", "passport.nationality"),
    FieldSpec("#passport-dob", "passport.date_of_birth"),
    FieldSpec("#passport-pob", "passport.place_of_birth"),
    FieldSpec("#passport-sex", "passport.sex", action="select_value"),
    FieldSpec("#passport-issue-date", "passport.date_of_issue"),
    FieldSpec("#passport-expiry-date", "passport.date_of_expiration"),
)
