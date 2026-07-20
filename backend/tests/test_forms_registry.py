"""Forms registry + library offline tests: the checked-in JSON must satisfy
the contract, and the downloader must refuse anything that isn't a verified
uscis.gov PDF. No network anywhere."""
import hashlib
import json

import httpx
import pytest

from app.forms.library import _fetch_one
from app.forms.registry import load_registry
from app.forms.schemas import FormRef, FormsRegistry, VisaProfile


def _form(**overrides):
    base = dict(
        form_id="I-129",
        title="Petition for a Nonimmigrant Worker",
        role="primary_petition",
        edition_date="01/17/25",
        form_page_url="https://www.uscis.gov/i-129",
        pdf_url="https://www.uscis.gov/sites/default/files/document/forms/i-129.pdf",
        issuing_agency="USCIS",
    )
    return FormRef(**{**base, **overrides})


# ---- schema guards ----

def test_pdf_url_must_be_uscis():
    with pytest.raises(ValueError):
        _form(pdf_url="https://evil.example/i-129.pdf")
    with pytest.raises(ValueError):
        _form(pdf_url="http://www.uscis.gov/i-129.pdf")  # https only


def test_form_page_must_be_official():
    with pytest.raises(ValueError):
        _form(form_page_url="https://formswiki.example/i-129")


def test_duplicate_form_role_rejected():
    with pytest.raises(ValueError):
        VisaProfile(
            visa_code="H-1B",
            category="nonimmigrant_employment",
            description="d",
            forms=[_form(), _form()],
        )


def test_duplicate_visa_codes_rejected():
    profile = VisaProfile(
        visa_code="H-1B", category="nonimmigrant_employment",
        description="d", forms=[_form()],
    )
    with pytest.raises(ValueError):
        FormsRegistry(
            version="1", researched_on="2026-07-19",
            visas=[profile, profile.model_copy()],
        )


def test_unique_pdf_forms_dedupes_preferring_editions():
    with_edition = _form()
    without = _form(edition_date=None)
    registry = FormsRegistry(
        version="1", researched_on="2026-07-19",
        visas=[
            VisaProfile(visa_code="A1", category="nonimmigrant_employment",
                        description="d", forms=[without]),
            VisaProfile(visa_code="B1", category="nonimmigrant_employment",
                        description="d", forms=[with_edition]),
        ],
    )
    unique = registry.unique_pdf_forms()
    assert len(unique) == 1
    assert unique[0].edition_date == "01/17/25"


# ---- the checked-in registry itself ----

def test_checked_in_registry_is_valid():
    registry = load_registry()  # raises loudly if missing or invalid
    assert registry.visas, "registry has no visa profiles"
    for profile in registry.visas:
        if profile.category == "cross_cutting":
            continue
        roles = {f.role for f in profile.forms}
        assert "primary_petition" in roles or "supplement" in roles, (
            f"{profile.visa_code} has no primary petition form"
        )


def test_registry_downloadable_set_nonempty():
    registry = load_registry()
    forms = registry.unique_pdf_forms()
    assert len(forms) >= 10, "expected a substantial downloadable form set"
    assert all(f.pdf_url.startswith("https://") for f in forms)


# ---- downloader (mock transport, no network) ----

PDF_BYTES = b"%PDF-1.7 fake body"


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_one_stores_verified_pdf(tmp_path):
    async def handler(request):
        return httpx.Response(200, content=PDF_BYTES)

    async with _client(handler) as client:
        entry = await _fetch_one(client, _form(), tmp_path)
    assert "error" not in entry
    stored = tmp_path / entry["file"]
    assert stored.read_bytes() == PDF_BYTES
    assert entry["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()


async def test_fetch_one_refuses_non_pdf_body(tmp_path):
    async def handler(request):
        return httpx.Response(200, content=b"<html>captcha wall</html>")

    async with _client(handler) as client:
        entry = await _fetch_one(client, _form(), tmp_path)
    assert "magic bytes" in entry["error"]
    assert list(tmp_path.iterdir()) == []  # nothing partial on disk


async def test_fetch_one_refuses_unlisted_host(tmp_path):
    form = _form()
    # bypass schema by mutating a copy's dict post-validation
    sneaky = form.model_copy(update={"pdf_url": "https://mirror.example/i-129.pdf"})

    async def handler(request):  # pragma: no cover - must never be called
        raise AssertionError("request must not be sent")

    async with _client(handler) as client:
        entry = await _fetch_one(client, sneaky, tmp_path)
    assert "not allow-listed" in entry["error"]
