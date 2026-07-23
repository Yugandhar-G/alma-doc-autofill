"""Seed idempotency + fidelity to the frozen checklist labels."""

from __future__ import annotations

from core import case_history
from core.db import connect_and_init
from seed import seed_case


def test_seed_is_idempotent(tmp_path):
    path = str(tmp_path / "seed.db")
    conn = connect_and_init(path)
    try:
        seed_case.seed(conn)
        seed_case.seed(conn)

        cases = conn.execute('SELECT COUNT(*) FROM "case"').fetchone()[0]
        clients = conn.execute("SELECT COUNT(*) FROM client").fetchone()[0]
        intakes = conn.execute("SELECT COUNT(*) FROM intake").fetchone()[0]
        items = conn.execute("SELECT COUNT(*) FROM checklist_item").fetchone()[0]

        assert cases == 1
        assert clients == 2
        assert intakes == 2
        assert items == 9
    finally:
        conn.close()


def test_seed_checklist_labels_verbatim(tmp_path):
    path = str(tmp_path / "seed.db")
    conn = connect_and_init(path)
    try:
        seed_case.seed(conn)
        rows = conn.execute(
            "SELECT seq, label, mandatory_to_file FROM checklist_item "
            "WHERE intake_id = ? ORDER BY seq",
            (seed_case.PETITIONER_INTAKE_ID,),
        ).fetchall()

        assert rows[0]["label"] == "2 Photographs (Passport style – front facing)"
        assert rows[0]["mandatory_to_file"] == 1
        # Items 3 and 5 are the only non-mandatory ones.
        non_mandatory = {r["seq"] for r in rows if r["mandatory_to_file"] == 0}
        assert non_mandatory == {3, 5}
        # All items start missing.
        states = {
            r["state"]
            for r in conn.execute("SELECT state FROM checklist_item").fetchall()
        }
        assert states == {"missing"}
    finally:
        conn.close()


def test_seed_case_history_idempotent_two_records(tmp_path):
    """Seeding twice yields exactly two history records (one per role), both
    carrying the firm case number on the same case."""
    path = str(tmp_path / "seed.db")
    conn = connect_and_init(path)
    try:
        seed_case.seed(conn)
        seed_case.seed(conn)

        records = case_history.get_history(conn, seed_case.CASE_ID)
        assert len(records) == 2

        roles = {r.role for r in records}
        assert roles == {"petitioner", "beneficiary"}

        for r in records:
            assert r.case_number == "YIL-2026-0001"
    finally:
        conn.close()


def test_seed_case_history_uscis_fields_null(tmp_path):
    """uscis_case_number and case_status are honestly absent at handoff, not guessed."""
    path = str(tmp_path / "seed.db")
    conn = connect_and_init(path)
    try:
        seed_case.seed(conn)

        for r in case_history.get_history(conn, seed_case.CASE_ID):
            assert r.uscis_case_number is None
            assert r.case_status is None
    finally:
        conn.close()


def test_seed_petitioner_has_citizenship(tmp_path):
    """The petitioner record carries the naturalization citizenship snapshot."""
    path = str(tmp_path / "seed.db")
    conn = connect_and_init(path)
    try:
        seed_case.seed(conn)

        records = case_history.get_history(conn, seed_case.CASE_ID, role="petitioner")
        assert len(records) == 1
        petitioner = records[0].petitioner
        assert petitioner is not None
        assert petitioner.citizenship is not None
        assert petitioner.citizenship.status == "U.S. Citizen"
        assert petitioner.citizenship.acquired_how == "Naturalization"
    finally:
        conn.close()


def test_seed_beneficiary_has_immigration(tmp_path):
    """The beneficiary record carries the F-1 immigration snapshot."""
    path = str(tmp_path / "seed.db")
    conn = connect_and_init(path)
    try:
        seed_case.seed(conn)

        records = case_history.get_history(conn, seed_case.CASE_ID, role="beneficiary")
        assert len(records) == 1
        beneficiary = records[0].beneficiary
        assert beneficiary is not None
        assert beneficiary.immigration is not None
        assert beneficiary.immigration.current_status == "F-1 Student"
        assert beneficiary.immigration.inspected_at_entry is True
    finally:
        conn.close()
