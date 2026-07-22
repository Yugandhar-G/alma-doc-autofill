"""DraftAction store tests — lifecycle + double-layer send guard (§4.2)."""

from __future__ import annotations

import sqlite3

import pytest

from core import drafts


def test_create_forces_pending(db, sample_draft):
    forced = sample_draft.model_copy(update={"state": "approved"})
    stored = drafts.create_draft(db, forced)
    assert stored.state == "pending"
    assert drafts.get_draft(db, stored.id).state == "pending"


def test_lifecycle_happy_path(db, sample_draft):
    d = drafts.create_draft(db, sample_draft)
    assert drafts.approve_draft(db, d.id).state == "approved"
    sent = drafts.mark_sent(db, d.id, mocked=True)
    assert sent.state == "sent"

    ledger = db.execute(
        "SELECT mocked FROM message_sent WHERE draft_id = ?", (d.id,)
    ).fetchone()
    assert ledger is not None and ledger["mocked"] == 1


def test_reject_from_pending(db, sample_draft):
    d = drafts.create_draft(db, sample_draft)
    assert drafts.reject_draft(db, d.id).state == "rejected"


def test_mark_sent_on_pending_raises_assertion_layer(db, sample_draft):
    """Enforcement layer 1: Python assertion fires before any UPDATE."""
    d = drafts.create_draft(db, sample_draft)
    with pytest.raises(AssertionError):
        drafts.mark_sent(db, d.id, mocked=True)
    assert drafts.get_draft(db, d.id).state == "pending"


def test_ledger_insert_on_pending_blocked_by_trigger(db, sample_draft):
    """Enforcement layer 3: the DB trigger blocks a message_sent row for a
    draft that never reached approved — independent of the Python guard."""
    d = drafts.create_draft(db, sample_draft)  # state pending
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO message_sent (id, draft_id, channel, sent_at, mocked) "
            "VALUES ('msg_x', ?, 'client_email', '2026-07-22T00:00:00+00:00', 1)",
            (d.id,),
        )


def test_double_approve_raises(db, sample_draft):
    d = drafts.create_draft(db, sample_draft)
    drafts.approve_draft(db, d.id)
    with pytest.raises(ValueError):
        drafts.approve_draft(db, d.id)
