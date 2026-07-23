"""Shared fixtures for the web-layer tests.

The domain bodies may not exist while the web layer is built, so every test
monkeypatches ``intake_workflow.domain.api`` functions. Cases are hand-built from the frozen
schemas (never from real domain behavior). The app runs against a throwaway
SQLite DB and uploads dir under ``tmp_path``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from intake_workflow.schemas import (
    Case,
    CaseProgress,
    CaseStage,
    CategoryCoverage,
    ChecklistItem,
    ItemKind,
    Party,
    PartyRole,
    QuestionField,
)

FIXED = datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc)


def _make_case(case_id: str = "case1") -> Case:
    petitioner = Party(
        role=PartyRole.petitioner, full_name="Ada Ramirez",
        email="ada@example.com", token="petitok",
    )
    beneficiary = Party(
        role=PartyRole.beneficiary, full_name="Kofi Osei",
        email="kofi@example.com", token="bentok",
    )
    items = [
        ChecklistItem(
            key="pet_bio", label="Petitioner — Biographic questionnaire",
            kind=ItemKind.question_section, assignee=PartyRole.petitioner,
            fields=[
                QuestionField(key="full_name", label="Full legal name"),
                QuestionField(key="dob", label="Date of birth", type="date"),
            ],
        ),
        ChecklistItem(
            key="marriage_cert", label="Marriage certificate",
            kind=ItemKind.document, assignee=PartyRole.petitioner,
        ),
        ChecklistItem(
            key="ben_passport", label="Beneficiary — Passport bio page",
            kind=ItemKind.document, assignee=PartyRole.beneficiary,
        ),
    ]
    return Case(
        id=case_id, title="Ramirez–Osei · Marriage AOS", created_at=FIXED,
        parties=[petitioner, beneficiary], items=items,
    )


def _make_progress(stage: CaseStage = CaseStage.in_progress, percent: int = 33) -> CaseProgress:
    return CaseProgress(
        required_total=3, accepted=1, percent=percent, stage=stage,
        coverage=[
            CategoryCoverage(category="financial", label="Financial commingling",
                             accepted=0, min_items=1, met=False),
        ],
        coverage_met=False,
    )


@pytest.fixture
def now() -> datetime:
    return FIXED


@pytest.fixture
def make_case():
    return _make_case


@pytest.fixture
def make_progress():
    return _make_progress


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YUNAKI_UPLOADS", str(tmp_path / "uploads"))
    # Default to demo mode so route tests hit the un-guarded path regardless of
    # the ambient environment. Auth tests re-set these via monkeypatch as needed.
    monkeypatch.delenv("YUNAKI_STAFF_PASSWORD", raising=False)
    monkeypatch.delenv("YUNAKI_SECRET", raising=False)
    from intake_workflow.main import create_app

    app = create_app()
    return TestClient(app)
