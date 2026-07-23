"""Shared fixtures for the phase-3 (filings / packets / eligibility) suite.

``tests/__init__.py`` + ``tests/phase3/__init__.py`` make the repo root the
rootdir pytest prepends to ``sys.path``, so ``import app`` resolves.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intake_workflow.domain import api
from intake_workflow.store import Store

# A fixed "now" so every timestamp/ordering assertion is deterministic.
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

# Complete, valid answers per question section (optional fields omitted).
VALID_ANSWERS = {
    "pet_bio": {
        "full_name": "Ana Marquez", "dob": "1988-04-12",
        "phone": "415-555-0100", "address": "1 Alder St, San Jose CA",
    },
    "ben_bio": {
        "full_name": "Wei Chen", "dob": "1990-02-02",
        "a_number": "A123456789", "i94_number": "AB1234567CD",
        "last_entry": "2022-01-01", "current_status": "F-1",
    },
    "marriage_details": {
        "marriage_date": "2023-06-15", "marriage_place": "San Jose, CA",
        "prior_marriages": "None",
    },
    "ben_address_history": {
        "current_address": "1 Alder St, San Jose CA", "moved_in": "2023-01-05",
    },
    "ben_eligibility": {
        "criminal_history": "No", "immigration_violations": "No",
        "prior_denials": "No",
    },
}


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


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


@pytest.fixture
def accepted_case(store, now, new_case):
    """A case whose question sections are all submitted and accepted, so the
    packet builder has real data to draw from."""
    case = new_case()
    for key in ("pet_bio", "ben_bio", "marriage_details", "ben_address_history"):
        api.submit_answers(store, case, key, case.item(key).assignee,
                           VALID_ANSWERS[key], now=now)
        api.review_item(store, case, key, action="accepted", reviewer="Isaiah",
                        now=now)
    return case
