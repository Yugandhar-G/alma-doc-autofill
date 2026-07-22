"""/yunaki status tests — DB-only snapshot, never-estimated values."""

from __future__ import annotations

from seed import seed_case
from slack_agent import status_command


def test_no_match(db):
    assert "No case on file" in status_command.handle_status(db, "nobody")


def test_multiple_matches_lists_them(db):
    db.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) VALUES '
        "('c1','Ravi Kumar','X','stage','2026-01-01T00:00:00+00:00')"
    )
    db.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) VALUES '
        "('c2','Ravi Patel','Y','stage','2026-01-01T00:00:00+00:00')"
    )
    db.commit()
    out = status_command.handle_status(db, "ravi")
    assert "Multiple cases match" in out
    assert "Ravi Kumar" in out and "Ravi Patel" in out


def test_seeded_case_snapshot_reports_not_on_file(db):
    seed_case.seed(db)
    out = status_command.handle_status(db, "ravi")
    assert "Ravi Kumar / Mei Lin" in out
    # No client activity yet → "not on file", never estimated.
    assert "last client activity not on file" in out
    # No deadline field exists → never a USCIS timeline from model knowledge.
    assert "Next deadline: not on file" in out
    # Checklist completeness computed from the DB.
    assert "Checklist:" in out and "of mandatory" in out
