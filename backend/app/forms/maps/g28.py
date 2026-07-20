"""G-28 (09/17/18 edition) PDF field map.

Field names verified against the library PDF's widget inventory 2026-07-19.
Sources resolve through the same {"g28": G28Data} dict the HTML population
engine uses — one extraction, two fill targets.

PDF-plane traps (mirror the HTML form's):
- Discipline 1.d is TWO independent checkboxes; Checkbox1dAm's PDF on-state
  is 'N' and Checkbox1dAmNot's is 'Y' — the engine sets True and lets the
  widget resolve its own on-state, touching exactly one of the pair.
- Unit type is three independent checkboxes (APT/STE/FLR) with padded
  on-states (' APT ' etc.); exactly one is checked per the extracted value.
- Line3d_State is a ComboBox whose option values are 2-letter codes, while
  extraction normalizes to full state names → action "combo_state".
- Signature/date-of-signature/Part 4 consent/barcode fields are structurally
  rejected by PdfFieldMap; they never appear here.
"""
from app.forms.fieldmap import PdfFieldMap, PdfFieldSpec

_P1 = "form1[0].#subform[0]"
_P2 = "form1[0].#subform[1]"

G28_PDF_MAP = PdfFieldMap(
    "G-28",
    (
        # ── Part 1 — Attorney ────────────────────────────────────────────
        PdfFieldSpec(f"{_P1}.#area[0].Pt1Line1_USCISOnlineAcctNumber[0]",
                     "g28.attorney.online_account_number"),
        PdfFieldSpec(f"{_P1}.Pt1Line2a_FamilyName[0]", "g28.attorney.family_name"),
        PdfFieldSpec(f"{_P1}.Pt1Line2b_GivenName[0]", "g28.attorney.given_name"),
        PdfFieldSpec(f"{_P1}.Pt1Line2c_MiddleName[0]", "g28.attorney.middle_name"),
        PdfFieldSpec(f"{_P1}.Line3a_StreetNumber[0]",
                     "g28.attorney.street_number_and_name"),
        PdfFieldSpec(f"{_P1}.Line3b_Unit[2]", "g28.attorney.apt_ste_flr",
                     action="checkbox", check_when="apt"),
        PdfFieldSpec(f"{_P1}.Line3b_Unit[0]", "g28.attorney.apt_ste_flr",
                     action="checkbox", check_when="ste"),
        PdfFieldSpec(f"{_P1}.Line3b_Unit[1]", "g28.attorney.apt_ste_flr",
                     action="checkbox", check_when="flr"),
        PdfFieldSpec(f"{_P1}.Line3b_AptSteFlrNumber[0]",
                     "g28.attorney.apt_ste_flr_number"),
        PdfFieldSpec(f"{_P1}.Line3c_CityOrTown[0]", "g28.attorney.city"),
        PdfFieldSpec(f"{_P1}.Line3d_State[0]", "g28.attorney.state",
                     action="combo_state"),
        PdfFieldSpec(f"{_P1}.Line3e_ZipCode[0]", "g28.attorney.zip_code"),
        PdfFieldSpec(f"{_P1}.Line3h_Country[0]", "g28.attorney.country"),
        PdfFieldSpec(f"{_P1}.Line4_DaytimeTelephoneNumber[0]",
                     "g28.attorney.daytime_phone"),
        PdfFieldSpec(f"{_P1}.Line7_MobileTelephoneNumber[0]",
                     "g28.attorney.mobile_phone"),
        PdfFieldSpec(f"{_P1}.Line6_EMail[0]", "g28.attorney.email"),
        # ── Part 2 — Eligibility ─────────────────────────────────────────
        PdfFieldSpec(f"{_P1}.CheckBox1[0]", "g28.eligibility.is_attorney",
                     action="checkbox", check_when=True),
        PdfFieldSpec(f"{_P1}.Pt2Line1a_LicensingAuthority[0]",
                     "g28.eligibility.licensing_authority"),
        PdfFieldSpec(f"{_P1}.Pt2Line1b_BarNumber[0]", "g28.eligibility.bar_number"),
        PdfFieldSpec(f"{_P1}.Checkbox1dAm[0]",
                     "g28.eligibility.subject_to_discipline",
                     action="checkbox", check_when=True),
        PdfFieldSpec(f"{_P1}.Checkbox1dAmNot[0]",
                     "g28.eligibility.subject_to_discipline",
                     action="checkbox", check_when=False),
        PdfFieldSpec(f"{_P1}.Pt2Line1d_NameofFirmOrOrganization[0]",
                     "g28.eligibility.law_firm"),
        PdfFieldSpec(f"{_P1}.CheckBox2[0]",
                     "g28.eligibility.is_accredited_representative",
                     action="checkbox", check_when=True),
        PdfFieldSpec(f"{_P1}.Line2b_NameofOrganization[0]",
                     "g28.eligibility.recognized_organization"),
        PdfFieldSpec(f"{_P1}.Line2c_DateExpires[0]",
                     "g28.eligibility.accreditation_date", action="date"),
        PdfFieldSpec(f"{_P1}.CheckBox3[0]", "g28.eligibility.is_associated",
                     action="checkbox", check_when=True),
        PdfFieldSpec(f"{_P1}.Line3_NameofAttorneyOrRep[0]",
                     "g28.eligibility.associated_with_name"),
        PdfFieldSpec(f"{_P1}.CheckBox4[0]", "g28.eligibility.is_law_student",
                     action="checkbox", check_when=True),
        PdfFieldSpec(f"{_P1}.Line4b_LawStudent[0]",
                     "g28.eligibility.law_student_name"),
        # ── Part 3 — Beneficiary (client) name ───────────────────────────
        PdfFieldSpec(f"{_P2}.Pt3Line5a_FamilyName[0]", "g28.beneficiary.family_name"),
        PdfFieldSpec(f"{_P2}.Pt3Line5b_GivenName[0]", "g28.beneficiary.given_name"),
        PdfFieldSpec(f"{_P2}.Pt3Line5c_MiddleName[0]", "g28.beneficiary.middle_name"),
    ),
)
