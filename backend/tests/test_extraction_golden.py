"""Golden extraction tests against real fixtures and the live Gemini API.

Results are cached in tests/.extraction_cache/ keyed by (file hash, model,
prompt hash) so reruns are free; set YUNAKI_REFRESH_EXTRACTION_CACHE=1 to force
a fresh API call. When GEMINI_API_KEY is unavailable and no cache exists,
tests SKIP (never fail).
"""
import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.extraction import extract_document, prompts
from app.schemas import DocType, ExtractionEnvelope

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CACHE_DIR = Path(__file__).parent / ".extraction_cache"
G28_FIXTURE = FIXTURES_DIR / "Example_G-28.pdf"
_PASSPORT_PATTERNS = ("passport_sample.jpg", "passport_sample.jpeg",
                      "passport_sample.png", "passport_sample.pdf")
_REFRESH_ENV = "YUNAKI_REFRESH_EXTRACTION_CACHE"


def _cache_path(file_bytes: bytes, doc_type: DocType) -> Path:
    settings = get_settings()
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    prompt_hash = hashlib.sha256(
        prompts.extraction_prompt(doc_type).encode()
    ).hexdigest()[:8]
    model_slug = settings.gemini_model.replace("/", "_")
    return CACHE_DIR / f"{doc_type}-{file_hash}-{model_slug}-{prompt_hash}.json"


def _extract_with_cache(fixture: Path, doc_type: DocType) -> ExtractionEnvelope:
    file_bytes = fixture.read_bytes()
    cache_path = _cache_path(file_bytes, doc_type)
    refresh = os.environ.get(_REFRESH_ENV) == "1"

    if cache_path.exists() and not refresh:
        return ExtractionEnvelope.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )

    if not get_settings().gemini_api_key:
        pytest.skip(
            f"GEMINI_API_KEY is not set and no cached extraction exists at "
            f"{cache_path.name} — set the key in backend/.env to run the "
            f"golden {doc_type} test live."
        )

    envelope = asyncio.run(extract_document(file_bytes, fixture.name, doc_type))
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    return envelope


def _dig(data: dict[str, Any], dotted_path: str) -> Any:
    value: Any = data
    for key in dotted_path.split("."):
        assert isinstance(value, dict), f"expected dict at {key!r} in {dotted_path!r}"
        value = value[key]
    return value


# --- G-28 golden -------------------------------------------------------------

@pytest.fixture(scope="module")
def g28_envelope() -> ExtractionEnvelope:
    if not G28_FIXTURE.exists():
        pytest.skip("Example_G-28.pdf fixture is absent (see tests/fixtures/README.md)")
    return _extract_with_cache(G28_FIXTURE, "g28")


G28_EXPECTED: list[tuple[str, Any]] = [
    # Values printed on the form
    ("attorney.family_name", "Smith"),
    ("attorney.given_name", "Barbara"),
    ("attorney.street_number_and_name", "545 Bryant Street"),
    ("attorney.city", "Palo Alto"),
    ("attorney.state", "California"),
    ("attorney.zip_code", "94301"),
    ("attorney.country", "United States of America"),
    ("attorney.email", "immigration@tryalma.ai"),
    ("eligibility.is_attorney", True),
    ("eligibility.licensing_authority", "State Bar of California"),
    ("eligibility.bar_number", "12083456"),
    ("eligibility.subject_to_discipline", False),
    ("eligibility.law_firm", "Alma Legal Services PC"),
    ("beneficiary.family_name", "Jonas"),
    ("beneficiary.given_name", "Joe"),
    # The N/A trap: fields marked "N/A" or left blank MUST be null, not guessed.
    # daytime_phone is BLANK on the form; the fax line holds 1650123456 and the
    # schema has no fax field — that value must drop, never land in daytime_phone.
    ("attorney.online_account_number", None),
    ("attorney.middle_name", None),
    ("attorney.apt_ste_flr", None),
    ("attorney.apt_ste_flr_number", None),
    ("attorney.daytime_phone", None),
    ("attorney.mobile_phone", None),
]


def test_fax_number_never_leaks_into_any_field(g28_envelope: ExtractionEnvelope) -> None:
    """The fax value is an unmapped source field; it must not appear anywhere."""
    assert g28_envelope.data is not None
    assert "1650123456" not in g28_envelope.model_dump_json()


def test_g28_detected_as_g28(g28_envelope: ExtractionEnvelope) -> None:
    assert g28_envelope.document_type_detected == "g28"
    assert g28_envelope.data is not None


def test_g28_source_hash_matches_input(g28_envelope: ExtractionEnvelope) -> None:
    expected = hashlib.sha256(G28_FIXTURE.read_bytes()).hexdigest()
    assert g28_envelope.source_hash == expected


def test_g28_model_recorded(g28_envelope: ExtractionEnvelope) -> None:
    assert g28_envelope.model_used


@pytest.mark.parametrize(("path", "expected"), G28_EXPECTED,
                         ids=[path for path, _ in G28_EXPECTED])
def test_g28_field(g28_envelope: ExtractionEnvelope, path: str, expected: Any) -> None:
    assert g28_envelope.data is not None
    assert _dig(g28_envelope.data, path) == expected


# --- Passport golden (activates when a fixture appears) ----------------------

@pytest.fixture(scope="module")
def passport_envelope() -> ExtractionEnvelope:
    fixture = next(
        (FIXTURES_DIR / name for name in _PASSPORT_PATTERNS
         if (FIXTURES_DIR / name).exists()),
        None,
    )
    if fixture is None:
        pytest.skip(
            "No passport fixture present — drop passport_sample.{jpg,png,pdf} "
            "into tests/fixtures/ to enable the passport golden test."
        )
    return _extract_with_cache(fixture, "passport")


def test_passport_detected_as_passport(passport_envelope: ExtractionEnvelope) -> None:
    assert passport_envelope.document_type_detected == "passport"
    assert passport_envelope.data is not None


def test_passport_dates_are_iso_or_null(passport_envelope: ExtractionEnvelope) -> None:
    """Contract check that holds for ANY passport: normalized dates and sex."""
    from datetime import datetime

    assert passport_envelope.data is not None
    for field in ("date_of_birth", "date_of_issue", "date_of_expiration"):
        value = passport_envelope.data[field]
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d")
    sex = passport_envelope.data["sex"]
    assert sex is None or sex in {"M", "F", "X"}
