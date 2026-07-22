"""Seed idempotency + fidelity to the frozen checklist labels."""

from __future__ import annotations

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
