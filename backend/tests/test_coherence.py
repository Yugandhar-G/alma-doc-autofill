"""Offline tests for the passport ↔ G-28 beneficiary coherence check."""
from app.extraction import check_coherence
from app.schemas import BeneficiaryInfo, G28Data, PassportData


def _g28(family: str | None, given: str | None) -> G28Data:
    return G28Data(beneficiary=BeneficiaryInfo(family_name=family, given_name=given))


def test_matching_names_produce_no_warnings() -> None:
    passport = PassportData(surname="Jonas", given_names="Joe")
    assert check_coherence(passport, _g28("Jonas", "Joe")) == []


def test_case_and_diacritic_noise_tolerated() -> None:
    passport = PassportData(surname="JONAS", given_names="joe")
    assert check_coherence(passport, _g28("Jonas", "Joe")) == []


def test_mismatched_surname_flagged() -> None:
    passport = PassportData(surname="Jonas", given_names="Joe")
    warnings = check_coherence(passport, _g28("Hernandez", "Joe"))
    assert [w.field for w in warnings] == ["beneficiary.family_name"]
    assert "similarity" in warnings[0].message


def test_both_fields_mismatched_flags_both() -> None:
    passport = PassportData(surname="Jonas", given_names="Joe")
    warnings = check_coherence(passport, _g28("Hernandez", "Maria"))
    assert {w.field for w in warnings} == {
        "beneficiary.family_name", "beneficiary.given_name"
    }


def test_nulls_are_skipped_not_flagged() -> None:
    passport = PassportData(surname=None, given_names="Joe")
    assert check_coherence(passport, _g28("Jonas", None)) == []
