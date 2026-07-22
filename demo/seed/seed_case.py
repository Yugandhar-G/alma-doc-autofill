"""Idempotent demo seed — CLAUDE_WORKPLAN.md §1.3 / §4.4.

Creates ONE fictional marriage case. FICTIONAL CAST ONLY — the real client
names from the firm recordings must never enter this repo (§4.4, enforced by
the pre-commit guard in scripts/check_no_real_pii.py).

Idempotency: every row uses a fixed deterministic id and is inserted with
INSERT OR IGNORE, so running the script any number of times yields exactly one
case with the same rows.

Checklist labels are copied VERBATIM from the firm's real petitioner
questionnaire (UI_DataModel_Reference §2). Do not paraphrase them.

Run: python -m seed.seed_case
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core.db import connect_and_init

# --------------------------------------------------------------------------- #
# Fixed fictional data. Deterministic ids make the seed idempotent.
# --------------------------------------------------------------------------- #

CASE_ID = "case_ravi_mei_demo"
PETITIONER_ID = "client_ravi_kumar_demo"
BENEFICIARY_ID = "client_mei_lin_demo"
PETITIONER_INTAKE_ID = "intake_ravi_demo"
BENEFICIARY_INTAKE_ID = "intake_mei_demo"

PROCESS_TYPE = "I-130 and I-485 One Step Marriage Based Green Cards"
STAGE = "USCIS-Case Opened (client's information/checklist pending)"

# (seq, label, mandatory_to_file) — labels VERBATIM from the real questionnaire.
PETITIONER_CHECKLIST: tuple[tuple[int, str, bool], ...] = (
    (1, "2 Photographs (Passport style – front facing)", True),
    (2, "Green Card or U.S. Birth Certificate, and U.S. Passport", True),
    (3, "Certificate of Naturalization/Citizenship (Must include if not born in the U.S.)", False),
    (4, "Petitioner and Beneficiary's marriage certificate", True),
    (5, "ALL Divorce decrees or death certificates of previous spouse(s), if any", False),
    (6, "Employment Verification letter", True),
    (7, "Federal Income Tax Return for most recent tax year", True),
    (8, "W-2's/1099s/K-1's/Copies of paycheck stubs of current job(s) for the past three months", True),
    (9, "Documents to prove a bona fide marriage", True),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed(conn: sqlite3.Connection) -> str:
    """Seed the fictional case idempotently. Returns the case id."""
    now = _now_iso()

    conn.execute(
        'INSERT OR IGNORE INTO "case" (id, name, process_type, stage, created_at) '
        "VALUES (?, ?, ?, ?, ?)",
        (CASE_ID, "Ravi Kumar / Mei Lin", PROCESS_TYPE, STAGE, now),
    )

    conn.execute(
        "INSERT OR IGNORE INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (PETITIONER_ID, "Ravi", "Kumar", "ravi.kumar.demo@example.com", "+1-555-0142", None),
    )
    conn.execute(
        "INSERT OR IGNORE INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (BENEFICIARY_ID, "Mei", "Lin", "mei.lin.demo@example.com", None, None),
    )

    conn.execute(
        "INSERT OR IGNORE INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
        (CASE_ID, PETITIONER_ID, "petitioner"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
        (CASE_ID, BENEFICIARY_ID, "beneficiary"),
    )

    for intake_id, client_id in (
        (PETITIONER_INTAKE_ID, PETITIONER_ID),
        (BENEFICIARY_INTAKE_ID, BENEFICIARY_ID),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO intake "
            "(id, case_id, client_id, url, state, sent_at, last_client_activity_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                intake_id,
                CASE_ID,
                client_id,
                f"https://intake.demo.local/i/{intake_id}",
                "sent",
                now,
                None,
            ),
        )

    for seq, label, mandatory in PETITIONER_CHECKLIST:
        conn.execute(
            "INSERT OR IGNORE INTO checklist_item "
            "(id, intake_id, seq, label, mandatory_to_file, state) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"chk_ravi_{seq:02d}",
                PETITIONER_INTAKE_ID,
                seq,
                label,
                1 if mandatory else 0,
                "missing",
            ),
        )

    conn.commit()
    return CASE_ID


def main() -> None:
    conn = connect_and_init()
    try:
        case_id = seed(conn)
        count = conn.execute('SELECT COUNT(*) FROM "case"').fetchone()[0]
        print(f"Seeded case {case_id!r}. Total cases in DB: {count}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
