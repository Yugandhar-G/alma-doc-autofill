"""Offline population-plane tests.

Runs populate_form headless against the saved form snapshot via a file://
URL — no network. Covers every action type, the duplicate-id middle-name
trap, label-vs-value selects, the pseudo-radio discipline pair, null
skipping, report aggregation, and a safety sweep proving no signature or
click pathways exist in the population code.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from app.population import demo as demo_module
from app.population import fill as fill_module
from app.population import verify as verify_module
from app.population.field_map import FIELD_MAP
from app.population.fill import populate_form, resolve_source
from app.schemas import G28Data, PassportData, PopulationEntry, PopulationReport

SNAPSHOT_URL = (Path(__file__).parent / "data" / "form_snapshot.html").resolve().as_uri()

FORBIDDEN_SELECTOR_FRAGMENTS = ("client-signature-date", "attorney-signature-date")


def make_passport() -> PassportData:
    return PassportData(
        surname="GONZALEZ",
        given_names="MARIA",
        middle_names="ELENA",
        passport_number="X1234567",
        country_of_issue="Mexico",
        nationality="Mexico",
        date_of_birth="1990-04-12",
        place_of_birth="Guadalajara",
        sex="F",
        date_of_issue="2020-01-15",
        date_of_expiration="2030-01-14",
    )


def make_g28() -> G28Data:
    return G28Data.model_validate(
        {
            "attorney": {
                "online_account_number": None,  # null → skipped_null
                "family_name": "Smith",
                "given_name": "John",
                "middle_name": None,            # null → skipped_null
                "street_number_and_name": "500 Market St",
                "apt_ste_flr": None,            # null → none of apt/ste/flr checked
                "apt_ste_flr_number": None,
                "city": "San Francisco",
                "state": "California",          # full label → option value CA
                "zip_code": "94105",
                "country": "United States",
                "daytime_phone": "415-555-0100",
                "mobile_phone": None,           # null → skipped_null
                "email": "john.smith@example.com",
            },
            "eligibility": {
                "is_attorney": True,
                "licensing_authority": "State Bar of California",
                "bar_number": "123456",
                "subject_to_discipline": False,  # → #not-subject checked, #am-subject untouched
                "law_firm": "Smith Immigration LLP",
                # accredited-rep / associated / law-student branches all null
            },
        }
    )


def entry_for(
    report: PopulationReport, selector: str, source: str | None = None
) -> PopulationEntry:
    matches = [
        e
        for e in report.entries
        if e.selector == selector and (source is None or e.source == source)
    ]
    assert len(matches) == 1, f"expected exactly one entry for {selector}/{source}, got {matches}"
    return matches[0]


@pytest.fixture(scope="module")
def report() -> PopulationReport:
    return asyncio.run(
        populate_form(make_passport(), make_g28(), headed=False, target_url=SNAPSHOT_URL)
    )


def test_report_counts_and_ok(report: PopulationReport) -> None:
    assert report.target_url == SNAPSHOT_URL
    assert len(report.entries) == len(FIELD_MAP)
    assert report.errors == 0
    assert report.mismatches == 0
    assert report.ok is True
    assert report.filled + report.skipped_null == len(FIELD_MAP)

    # skipped_null must equal the number of specs whose source resolves to None.
    sources = {"passport": make_passport().model_dump(), "g28": make_g28().model_dump()}
    expected_skips = sum(
        1 for spec in FIELD_MAP if resolve_source(sources, spec.source) is None
    )
    assert report.skipped_null == expected_skips
    assert expected_skips > 0  # the dataset deliberately contains several nulls


def test_middle_name_duplicate_id_trap(report: PopulationReport) -> None:
    first = entry_for(report, 'input[name="passport-given-names"]', "passport.given_names")
    middle = entry_for(report, 'input[name="passport-given-names"]', "passport.middle_names")
    # After the WHOLE run the first input still holds the first name and the
    # second input holds the middle name (read back post-run by verify.py).
    assert first.status == "filled"
    assert first.actual == "MARIA"
    assert middle.status == "filled"
    assert middle.actual == "ELENA"


def test_state_selected_by_label(report: PopulationReport) -> None:
    entry = entry_for(report, "#state")
    assert entry.status == "filled"
    assert entry.actual == "CA"  # label "California" → option VALUE "CA"


def test_sex_selected_by_value(report: PopulationReport) -> None:
    entry = entry_for(report, "#passport-sex")
    assert entry.status == "filled"
    assert entry.actual == "F"


def test_date_fields_hold_iso_values(report: PopulationReport) -> None:
    assert entry_for(report, "#passport-dob").actual == "1990-04-12"
    assert entry_for(report, "#passport-expiry-date").actual == "2030-01-14"


def test_discipline_pseudo_radio_pair(report: PopulationReport) -> None:
    not_subject = entry_for(report, "#not-subject")
    am_subject = entry_for(report, "#am-subject")
    assert not_subject.status == "filled"
    assert not_subject.actual == "checked"
    assert am_subject.status == "filled"
    assert am_subject.actual == "unchecked"  # never touched, verified untouched


def test_attorney_eligible_checked(report: PopulationReport) -> None:
    entry = entry_for(report, "#attorney-eligible")
    assert entry.status == "filled"
    assert entry.actual == "checked"


def test_apt_ste_flr_null_leaves_all_boxes_unchecked(report: PopulationReport) -> None:
    for selector in ("#apt", "#ste", "#flr"):
        entry = entry_for(report, selector)
        assert entry.status == "skipped_null"
        assert entry.expected is None
        assert entry.actual == "unchecked"  # audit read-back: box never touched
    assert entry_for(report, "#apt-number").status == "skipped_null"


def test_null_sources_are_skipped(report: PopulationReport) -> None:
    for selector in ("#online-account", "#middle-name", "#mobile-phone", "#recognized-org"):
        entry = entry_for(report, selector)
        assert entry.status == "skipped_null"
        assert entry.expected is None


def test_missing_g28_document_skips_all_g28_fields() -> None:
    report = asyncio.run(
        populate_form(make_passport(), None, headed=False, target_url=SNAPSHOT_URL)
    )
    assert report.ok is True
    assert report.errors == 0
    for entry in report.entries:
        if entry.source.startswith("g28."):
            assert entry.status == "skipped_null", entry
    assert entry_for(report, "#passport-surname").status == "filled"


def test_artifact_captured_and_downloadable(report: PopulationReport) -> None:
    """A headless run must persist a real PDF of the filled form, keyed by
    content hash, retrievable through the artifact resolver."""
    from app.population.artifact import stored_artifact_path

    assert report.artifact_kind == "pdf"
    assert report.artifact_id is not None and len(report.artifact_id) == 64
    path = stored_artifact_path(report.artifact_id)
    assert path is not None and path.exists()
    assert path.read_bytes().startswith(b"%PDF")


def test_artifact_resolver_rejects_non_hash_ids() -> None:
    from app.population.artifact import stored_artifact_path

    for bad in ("../../etc/passwd", "zz" * 32, "a" * 63, "", "a" * 64 + "/x"):
        assert stored_artifact_path(bad) is None


def test_field_map_contains_no_signature_or_submit_selectors() -> None:
    selector_union = " ".join(spec.selector for spec in FIELD_MAP)
    for fragment in FORBIDDEN_SELECTOR_FRAGMENTS:
        assert fragment not in selector_union


def test_population_code_never_clicks() -> None:
    for module in (fill_module, verify_module, demo_module):
        source = inspect.getsource(module)
        assert ".click(" not in source, f"{module.__name__} must never click"
        for fragment in FORBIDDEN_SELECTOR_FRAGMENTS:
            assert fragment not in source, f"{module.__name__} references {fragment}"
