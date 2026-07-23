"""Shared fixtures for the domain test suite.

``tests/__init__.py`` + ``tests/domain/__init__.py`` make the repo root the
rootdir pytest prepends to ``sys.path``, so ``import app`` resolves without a
root conftest.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pypdf import PdfWriter

from intake_workflow.domain import api
from intake_workflow.store import Store

# A fixed "now" so every ladder/stage/date assertion is deterministic.
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

# Valid questionnaire answers keyed by template item key (optional fields omitted).
VALID_ANSWERS = {
    "pet_bio": {
        "full_name": "Ana Marquez", "dob": "1988-04-12",
        "phone": "415-555-0100", "address": "1 Alder St, San Jose CA",
    },
    "ben_bio": {
        "full_name": "Wei Chen", "dob": "1990-02-02",
        "last_entry": "2022-01-01", "current_status": "F-1",
    },
    "marriage_details": {
        "marriage_date": "2023-06-15", "marriage_place": "San Jose, CA",
        "prior_marriages": "None",
    },
    "ben_eligibility": {
        "criminal_history": "No", "immigration_violations": "No",
        "prior_denials": "No",
    },
    "ben_address_history": {
        "current_address": "1 Alder St, San Jose CA", "moved_in": "2023-01-05",
    },
}


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


@pytest.fixture
def make_pdf(tmp_path):
    """Factory writing a valid PDF. pad_bytes>=~20KB clears the too_small floor;
    pad_bytes=0 yields a tiny scan that trips too_small."""
    def _make(name="doc.pdf", pages=1, pad_bytes=48 * 1024):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=612, height=792)
        if pad_bytes:
            writer.add_metadata({"/Comment": "x" * pad_bytes})
        path = tmp_path / name
        with open(path, "wb") as fh:
            writer.write(fh)
        return str(path)
    return _make


@pytest.fixture
def new_case(store, now):
    """Factory creating a fresh marriage-AOS case (all items pending)."""
    def _make(**overrides):
        params = dict(
            title="Marquez ↔ Chen — Marriage AOS",
            petitioner_name="Ana Marquez",
            petitioner_email="p@example.com",
            beneficiary_name="Wei Chen",
            beneficiary_email="b@example.com",
        )
        params.update(overrides)
        return api.create_case(store, now=now, **params)
    return _make
