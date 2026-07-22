"""LIVE_MODE gate tests — §4.1. Mock mode never calls the sender; live mode does
and logs a loud warning."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from core import drafts, events, sendgate


def _approved(db, sample_draft):
    d = drafts.create_draft(db, sample_draft)
    drafts.approve_draft(db, d.id)
    return d


def test_live_mode_false_writes_outbox_and_never_sends(db, sample_draft, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    d = _approved(db, sample_draft)
    sender = Mock()

    result = sendgate.execute_draft(db, d.id, sender)

    sender.assert_not_called()
    assert result["mocked"] is True

    outbox = db.execute(
        "SELECT live_mode_at_render FROM outbox WHERE draft_id = ?", (d.id,)
    ).fetchone()
    assert outbox is not None and outbox["live_mode_at_render"] == 0

    msg_events = events.query_events(db, type="message.sent")
    assert len(msg_events) == 1
    assert msg_events[0].payload["mocked"] is True

    assert drafts.get_draft(db, d.id).state == "sent"


def test_live_mode_true_calls_sender_and_logs_loud(db, sample_draft, monkeypatch, caplog):
    monkeypatch.setenv("LIVE_MODE", "true")
    d = _approved(db, sample_draft)
    sender = Mock()

    with caplog.at_level(logging.CRITICAL, logger="yunaki.sendgate"):
        result = sendgate.execute_draft(db, d.id, sender)

    sender.assert_called_once()
    assert result["mocked"] is False and result["live_mode"] is True

    loud = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert loud and "LIVE_MODE ACTIVE" in loud[0].getMessage()

    outbox = db.execute(
        "SELECT live_mode_at_render FROM outbox WHERE draft_id = ?", (d.id,)
    ).fetchone()
    assert outbox["live_mode_at_render"] == 1

    ledger = db.execute(
        "SELECT mocked FROM message_sent WHERE draft_id = ?", (d.id,)
    ).fetchone()
    assert ledger["mocked"] == 0


def test_execute_requires_approved_draft(db, sample_draft, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    d = drafts.create_draft(db, sample_draft)  # still pending
    with pytest.raises(ValueError):
        sendgate.execute_draft(db, d.id, Mock())
