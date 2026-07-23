"""Case-history store tests — contract, idempotency, upsert, audit payload.

Covers: role/payload mismatch rejected; stub idempotent + null-over-guess;
upsert preserves case_number + created_at and bumps updated_at; UNIQUE(case_id,
role) overwrite semantics; get_history role filter; next_case_number increment +
zero-pad; PII-FREE `case_history.updated` payload; set_uscis roundtrip + LookupError.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from core import case_history as ch
from core import events
from core.case_history import (
    BeneficiaryHistory,
    CaseHistoryRecord,
    PersonName,
    PetitionerHistory,
)


CASE_ID = "case_ravi_mei_demo"


def _seed_case(conn: sqlite3.Connection, case_id: str = CASE_ID) -> None:
    """Case row must exist first — case_history.case_id is an FK to "case"(id)."""
    conn.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) '
        "VALUES (?, ?, ?, ?, ?)",
        (case_id, "Ravi & Mei", "marriage_aos", "USCIS-Case Opened", "2026-07-23T00:00:00+00:00"),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Contract: role/payload consistency
# --------------------------------------------------------------------------- #

def test_role_petitioner_requires_petitioner_only():
    with pytest.raises(ValidationError):
        CaseHistoryRecord(
            case_id=CASE_ID,
            role="petitioner",
            beneficiary=BeneficiaryHistory(),  # wrong side populated
        )


def test_role_beneficiary_rejects_petitioner_set():
    with pytest.raises(ValidationError):
        CaseHistoryRecord(
            case_id=CASE_ID,
            role="beneficiary",
            beneficiary=BeneficiaryHistory(),
            petitioner=PetitionerHistory(),  # both sides populated
        )


def test_role_petitioner_missing_model_rejected():
    with pytest.raises(ValidationError):
        CaseHistoryRecord(case_id=CASE_ID, role="petitioner")


# --------------------------------------------------------------------------- #
# create_stub: minimal, idempotent, null-over-guess
# --------------------------------------------------------------------------- #

def test_create_stub_sets_only_given_basics(db):
    _seed_case(db)
    rec = ch.create_stub(
        db,
        case_id=CASE_ID,
        role="petitioner",
        first_name="Ravi",
        last_name="Kumar",
        email="ravi.kumar.demo@example.com",
        phone="+15550001111",
    )
    p = rec.petitioner
    assert p is not None and rec.beneficiary is None
    assert p.legal_name.first == "Ravi"
    assert p.legal_name.last == "Kumar"
    assert p.legal_name.middle is None
    assert p.email == "ravi.kumar.demo@example.com"
    assert p.phones.mobile == "+15550001111"
    # null over guess: nothing else invented
    assert p.a_number is None
    assert p.date_of_birth is None
    assert p.marriage_history == []
    assert p.father is None


def test_create_stub_is_idempotent_no_second_event(db):
    _seed_case(db)
    seen: list = []
    events.subscribe("case_history.updated", seen.append)

    first = ch.create_stub(db, case_id=CASE_ID, role="petitioner", first_name="Ravi")
    second = ch.create_stub(db, case_id=CASE_ID, role="petitioner", first_name="IGNORED")

    # existing record returned UNCHANGED
    assert second.id == first.id
    assert second.petitioner.legal_name.first == "Ravi"
    # exactly one event fired (NEW row only)
    assert len(seen) == 1
    rows = db.execute("SELECT COUNT(*) AS n FROM case_history").fetchone()
    assert rows["n"] == 1


# --------------------------------------------------------------------------- #
# upsert_history: preserve case_number + created_at, bump updated_at, overwrite
# --------------------------------------------------------------------------- #

def test_upsert_preserves_case_number_and_created_at_bumps_updated(db):
    _seed_case(db)
    stub = ch.create_stub(
        db, case_id=CASE_ID, role="petitioner", first_name="Ravi",
        case_number="YIL-2026-0001",
    )
    original_created = stub.created_at

    # Nanda's full submit arrives WITHOUT a case_number — must be preserved.
    incoming = CaseHistoryRecord(
        case_id=CASE_ID,
        role="petitioner",
        case_number=None,
        petitioner=PetitionerHistory(
            legal_name=PersonName(first="Ravi", middle="Anand", last="Kumar"),
            date_of_birth="1990-05-01",
            marriage_history=[],
        ),
    )
    stored = ch.upsert_history(db, incoming)

    assert stored.case_number == "YIL-2026-0001"  # preserved
    assert stored.created_at == original_created  # preserved
    assert stored.updated_at >= original_created  # bumped (fresh)
    assert stored.petitioner.date_of_birth == "1990-05-01"  # merged/overwritten
    assert stored.petitioner.legal_name.middle == "Anand"


def test_upsert_overwrites_single_row(db):
    _seed_case(db)
    ch.create_stub(db, case_id=CASE_ID, role="beneficiary", first_name="Mei")

    first = CaseHistoryRecord(
        case_id=CASE_ID, role="beneficiary",
        beneficiary=BeneficiaryHistory(birth_country="China"),
    )
    ch.upsert_history(db, first)
    second = CaseHistoryRecord(
        case_id=CASE_ID, role="beneficiary",
        beneficiary=BeneficiaryHistory(birth_country="Taiwan"),
    )
    stored = ch.upsert_history(db, second)

    assert stored.beneficiary.birth_country == "Taiwan"  # overwritten
    n = db.execute(
        "SELECT COUNT(*) AS n FROM case_history WHERE case_id = ? AND role = ?",
        (CASE_ID, "beneficiary"),
    ).fetchone()["n"]
    assert n == 1  # UNIQUE(case_id, role) — still one row


def test_upsert_can_set_case_number_when_provided(db):
    _seed_case(db)
    ch.create_stub(db, case_id=CASE_ID, role="petitioner", first_name="Ravi")
    incoming = CaseHistoryRecord(
        case_id=CASE_ID, role="petitioner", case_number="YIL-2026-0042",
        petitioner=PetitionerHistory(legal_name=PersonName(first="Ravi")),
    )
    stored = ch.upsert_history(db, incoming)
    assert stored.case_number == "YIL-2026-0042"


# --------------------------------------------------------------------------- #
# get_history role filter
# --------------------------------------------------------------------------- #

def test_get_history_role_filter(db):
    _seed_case(db)
    ch.create_stub(db, case_id=CASE_ID, role="petitioner", first_name="Ravi")
    ch.create_stub(db, case_id=CASE_ID, role="beneficiary", first_name="Mei")

    both = ch.get_history(db, CASE_ID)
    assert len(both) == 2

    only_pet = ch.get_history(db, CASE_ID, role="petitioner")
    assert len(only_pet) == 1
    assert only_pet[0].role == "petitioner"
    assert only_pet[0].beneficiary is None


def test_get_history_empty_case(db):
    _seed_case(db)
    assert ch.get_history(db, CASE_ID) == []


# --------------------------------------------------------------------------- #
# next_case_number: increment + zero-pad
# --------------------------------------------------------------------------- #

def test_next_case_number_increments_and_zero_pads(db):
    first = ch.next_case_number(db)
    second = ch.next_case_number(db)
    year = first.split("-")[1]
    assert first == f"YIL-{year}-0001"
    assert second == f"YIL-{year}-0002"


# --------------------------------------------------------------------------- #
# Event payload is PII-FREE
# --------------------------------------------------------------------------- #

def test_updated_event_payload_is_pii_free(db):
    _seed_case(db)
    captured: list = []
    events.subscribe("case_history.updated", captured.append)

    ch.create_stub(
        db, case_id=CASE_ID, role="petitioner",
        first_name="Ravi", last_name="Kumar",
        email="ravi.kumar.demo@example.com", phone="+15550001111",
    )
    assert len(captured) == 1
    payload = captured[0].payload
    assert payload["role"] == "petitioner"
    # legal_name.first + legal_name.last + email + phones.mobile = 4 leaves
    assert payload["fields_present"] == 4
    assert payload["has_uscis_number"] is False
    assert payload["has_case_status"] is False

    blob = str(payload)
    assert "Ravi" not in blob
    assert "Kumar" not in blob
    assert "ravi.kumar.demo@example.com" not in blob
    assert "+15550001111" not in blob


def test_upsert_event_payload_reflects_uscis_and_status(db):
    _seed_case(db)
    ch.create_stub(db, case_id=CASE_ID, role="petitioner", first_name="Ravi")
    captured: list = []
    events.subscribe("case_history.updated", captured.append)

    incoming = CaseHistoryRecord(
        case_id=CASE_ID, role="petitioner",
        uscis_case_number="IOE0000000001", case_status="Received",
        petitioner=PetitionerHistory(legal_name=PersonName(first="Ravi")),
    )
    ch.upsert_history(db, incoming)
    payload = captured[0].payload
    assert payload["has_uscis_number"] is True
    assert payload["has_case_status"] is True
    assert payload["fields_present"] == 1  # only legal_name.first


# --------------------------------------------------------------------------- #
# set_uscis roundtrip + LookupError
# --------------------------------------------------------------------------- #

def test_set_uscis_roundtrip(db):
    _seed_case(db)
    ch.create_stub(db, case_id=CASE_ID, role="petitioner", first_name="Ravi")
    updated = ch.set_uscis(
        db, CASE_ID, "petitioner",
        uscis_case_number="IOE0000000002", case_status="Case Was Received",
    )
    assert updated.uscis_case_number == "IOE0000000002"
    assert updated.case_status == "Case Was Received"

    # partial update preserves the untouched field
    again = ch.set_uscis(db, CASE_ID, "petitioner", case_status="Fingerprints Taken")
    assert again.uscis_case_number == "IOE0000000002"  # preserved
    assert again.case_status == "Fingerprints Taken"


def test_set_uscis_missing_record_raises(db):
    _seed_case(db)
    with pytest.raises(LookupError):
        ch.set_uscis(db, CASE_ID, "petitioner", uscis_case_number="IOE0000000003")


# --------------------------------------------------------------------------- #
# Fresh-DB roundtrip (success criterion 2)
# --------------------------------------------------------------------------- #

def test_full_roundtrip_stub_then_upsert_merges(db):
    _seed_case(db)
    ch.create_stub(
        db, case_id=CASE_ID, role="petitioner", first_name="Ravi",
        case_number="YIL-2026-0007",
    )
    full = CaseHistoryRecord(
        case_id=CASE_ID, role="petitioner", case_number=None,
        petitioner=PetitionerHistory(
            legal_name=PersonName(first="Ravi", last="Kumar"),
            date_of_birth="1990-05-01",
            birth_country="India",
        ),
    )
    ch.upsert_history(db, full)

    got = ch.get_history(db, CASE_ID, role="petitioner")
    assert len(got) == 1
    rec = got[0]
    assert rec.case_number == "YIL-2026-0007"  # preserved through upsert
    assert rec.petitioner.birth_country == "India"
    assert rec.petitioner.date_of_birth == "1990-05-01"
