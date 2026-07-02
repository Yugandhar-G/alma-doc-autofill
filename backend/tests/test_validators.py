"""Offline tests for post-extraction validators: dates, sex, US states,
and the null-plus-warning failure mode."""
import pytest

from app.extraction.validators import (
    US_STATES,
    check_date,
    check_sex,
    check_state,
    validate_g28,
    validate_passport,
)
from app.schemas import AttorneyInfo, G28Data, PassportData


class TestCheckDate:
    @pytest.mark.parametrize("value", ["2020-01-05", "1999-12-31", " 2020-01-05 "])
    def test_valid_dates_pass_trimmed(self, value: str) -> None:
        result, warning = check_date(value, "date_of_birth")
        assert result == value.strip()
        assert warning is None

    def test_unpadded_date_canonicalized(self) -> None:
        result, warning = check_date("2020-1-5", "date_of_birth")
        assert result == "2020-01-05"
        assert warning is None

    @pytest.mark.parametrize(
        "value", ["01/05/2020", "2020-13-01", "2020-02-30", "not a date", "05-01-2020"]
    )
    def test_invalid_dates_nulled_with_warning(self, value: str) -> None:
        result, warning = check_date(value, "date_of_birth")
        assert result is None
        assert warning is not None
        assert warning.field == "date_of_birth"

    def test_none_and_blank_pass_silently(self) -> None:
        assert check_date(None, "f") == (None, None)
        assert check_date("   ", "f") == (None, None)


class TestCheckSex:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("M", "M"), ("F", "F"), ("X", "X"), ("m", "M"),
         ("MALE", "M"), ("Female", "F"), (" M ", "M")],
    )
    def test_normalization(self, value: str, expected: str) -> None:
        result, warning = check_sex(value, "sex")
        assert result == expected
        assert warning is None

    @pytest.mark.parametrize("value", ["Q", "unknown", "MF"])
    def test_invalid_nulled_with_warning(self, value: str) -> None:
        result, warning = check_sex(value, "sex")
        assert result is None
        assert warning is not None


class TestCheckState:
    def test_domain_data_complete(self) -> None:
        assert len(US_STATES) == 51  # 50 states + District of Columbia
        assert "District of Columbia" in US_STATES

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("California", "california_exact"), ("CA", "abbrev"), ("ca", "abbrev_lower"),
         ("  California  ", "whitespace"), ("california", "casefold"),
         ("D.C.", "dotted_abbrev")],
    )
    def test_normalization(self, value: str, expected: str) -> None:
        result, warning = check_state(value, "attorney.state")
        assert result in US_STATES
        assert warning is None

    def test_ca_maps_to_california(self) -> None:
        assert check_state("CA", "attorney.state")[0] == "California"

    @pytest.mark.parametrize("value", ["Cascadia", "XX", "Ontario", "Puerto Rico"])
    def test_non_states_nulled_with_warning(self, value: str) -> None:
        result, warning = check_state(value, "attorney.state")
        assert result is None
        assert warning is not None
        assert warning.field == "attorney.state"


class TestValidatePassport:
    def test_immutability_and_warnings(self) -> None:
        original = PassportData(
            surname="García", date_of_birth="01/02/1990", sex="MALE",
            date_of_issue="2020-01-01", date_of_expiration="2030-01-01",
        )
        validated, warnings = validate_passport(original)
        assert validated is not original
        assert original.date_of_birth == "01/02/1990"  # input untouched
        assert validated.date_of_birth is None
        assert validated.sex == "M"
        assert validated.date_of_issue == "2020-01-01"
        assert validated.surname == "García"
        assert [w.field for w in warnings] == ["date_of_birth"]

    def test_clean_passport_no_warnings(self) -> None:
        data = PassportData(date_of_birth="1990-02-01", sex="F")
        validated, warnings = validate_passport(data)
        assert warnings == []
        assert validated.model_dump() == data.model_dump()


class TestValidateG28:
    def test_state_abbrev_normalized(self) -> None:
        data = G28Data(attorney=AttorneyInfo(state="CA"))
        validated, warnings = validate_g28(data)
        assert validated.attorney.state == "California"
        assert warnings == []
        assert data.attorney.state == "CA"  # input untouched

    def test_bad_state_and_date_both_warned(self) -> None:
        data = G28Data(attorney=AttorneyInfo(state="Narnia"))
        data = data.model_copy(
            update={"eligibility": data.eligibility.model_copy(
                update={"accreditation_date": "12/31/2020"})}
        )
        validated, warnings = validate_g28(data)
        assert validated.attorney.state is None
        assert validated.eligibility.accreditation_date is None
        assert {w.field for w in warnings} == {
            "attorney.state", "eligibility.accreditation_date"
        }
