"""Native PDF fill engine tests. Map guards and converters are pure; the
end-to-end fill uses the downloaded G-28 library PDF and skips (not fails)
when the library hasn't been fetched — same policy as the golden tests."""
from pathlib import Path

import pytest

from app.forms.fieldmap import (
    PdfFieldMap, PdfFieldSpec, iso_to_uscis_date, state_to_code,
)
from app.forms.library import LIBRARY_DIR
from app.schemas.g28 import AttorneyInfo, BeneficiaryInfo, EligibilityInfo, G28Data

G28_PDF_PRESENT = bool(sorted(Path(LIBRARY_DIR).glob("G-28__*.pdf")))


# ---- structural guards (pure) ----

def test_signature_and_barcode_fields_are_unmappable():
    for bad in (
        "form1[0].#subform[2].Line1_Signature[0]",
        "form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]",
        "form1[0].#subform[2].Pt4Line2a_CheckBox2a[0]",
        "form1[0].#subform[2].Pt5Line2b_DateofSignature[0]",
    ):
        with pytest.raises(ValueError, match="forbidden"):
            PdfFieldMap("X-1", (PdfFieldSpec(bad, "g28.attorney.city"),))


def test_duplicate_text_mapping_rejected():
    spec = PdfFieldSpec("form1[0].#subform[0].Line6_EMail[0]", "g28.attorney.email")
    with pytest.raises(ValueError, match="duplicate"):
        PdfFieldMap("X-1", (spec, spec))


def test_converters():
    assert state_to_code("California") == "CA"
    assert state_to_code("ny") == "NY"
    with pytest.raises(ValueError):
        state_to_code("Cascadia")
    assert iso_to_uscis_date("2026-01-20") == "01/20/2026"
    with pytest.raises(ValueError):
        iso_to_uscis_date("01/20/2026")  # non-ISO input is a contract violation


# ---- end-to-end fill against the real library PDF ----

SAMPLE = G28Data(
    attorney=AttorneyInfo(
        family_name="Nguyen", given_name="Mai", middle_name=None,
        street_number_and_name="12 Market St", apt_ste_flr="ste",
        apt_ste_flr_number="400", city="San Jose", state="California",
        zip_code="95113", country="United States of America",
        daytime_phone="4085550100", email="mai@firm.example",
        online_account_number=None, mobile_phone=None,
    ),
    eligibility=EligibilityInfo(
        is_attorney=True, licensing_authority="State Bar of California",
        bar_number="123456", subject_to_discipline=False,
        law_firm="Nguyen Immigration LLP",
    ),
    beneficiary=BeneficiaryInfo(family_name="Rossi", given_name="Elena"),
)


@pytest.mark.skipif(not G28_PDF_PRESENT, reason="forms library not fetched")
def test_fill_g28_end_to_end(tmp_path):
    import fitz

    from app.forms.fill import fill_pdf

    out = tmp_path / "g28_filled.pdf"
    report = fill_pdf("G-28", {"g28": SAMPLE.model_dump()}, out)

    assert report.verified, [r for r in report.results if r.status not in ("filled", "skipped_null")]
    assert report.xfa_stripped
    filled = {r.field: r for r in report.results if r.status == "filled"}
    skipped = {r.field for r in report.results if r.status == "skipped_null"}

    # state combobox got the code, date-free text got exact values
    assert filled["form1[0].#subform[0].Line3d_State[0]"].actual == "CA"
    assert filled["form1[0].#subform[0].Pt1Line2a_FamilyName[0]"].actual == "Nguyen"

    # nulls skipped, never typed
    assert "form1[0].#subform[0].Pt1Line2c_MiddleName[0]" in skipped
    assert "form1[0].#subform[0].Line7_MobileTelephoneNumber[0]" in skipped

    # discipline trap: exactly one of the pair; 'am' box untouched (False case)
    assert "form1[0].#subform[0].Checkbox1dAm[0]" in skipped
    assert "form1[0].#subform[0].Checkbox1dAmNot[0]" in filled

    # unit trap: STE checked, APT/FLR untouched
    assert "form1[0].#subform[0].Line3b_Unit[0]" in filled
    assert "form1[0].#subform[0].Line3b_Unit[2]" in skipped

    # output artifact really has no XFA and library copy is untouched
    check = fitz.open(str(out))
    catalog = check.pdf_catalog()
    acro_type, acro_val = check.xref_get_key(catalog, "AcroForm")
    if acro_type == "xref":
        assert check.xref_get_key(int(acro_val.split()[0]), "XFA")[0] == "null"
    check.close()

    from app.forms.fill import library_pdf_path
    lib = fitz.open(library_pdf_path("G-28"))
    lib_catalog = lib.pdf_catalog()
    lt, lv = lib.xref_get_key(lib_catalog, "AcroForm")
    if lt == "xref":
        assert lib.xref_get_key(int(lv.split()[0]), "XFA")[0] != "null"
    lib.close()


@pytest.mark.skipif(not G28_PDF_PRESENT, reason="forms library not fetched")
def test_fill_unknown_form_and_missing_map_fail_loud(tmp_path):
    from app.forms.fill import fill_pdf

    with pytest.raises(KeyError):
        fill_pdf("I-129", {"g28": {}}, tmp_path / "x.pdf")  # no map registered yet
