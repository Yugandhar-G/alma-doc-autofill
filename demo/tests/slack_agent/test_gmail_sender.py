"""Gmail sender through the sendgate: LIVE_MODE=false never touches the API;
LIVE_MODE=true sends exactly the approved draft. §4.1/§4.2 end to end."""

from __future__ import annotations

import base64
from email import message_from_bytes

import pytest

from core.drafts import approve_draft, create_draft
from core.models import DraftAction, DraftTo
from core.sendgate import execute_draft
from gmail_agent.sender import build_gmail_sender
from seed.seed_case import seed


class _SendRecorder:
    """Fake gmail service recording users().messages().send() calls."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):  # noqa: N803 - API shape
        self.sent.append(body)
        return _Result({"id": "sent_1"})


class _Result:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


def _approved_draft(db) -> DraftAction:
    case_id = seed(db)
    draft = create_draft(
        db,
        DraftAction(
            case_id=case_id,
            kind="client_email",
            trigger="manual",
            to=DraftTo(name="Mei Lin", channel_address="mei.lin.demo@example.com"),
            subject="Your documents",
            body="Hi Mei, two items are still missing.",
        ),
    )
    return approve_draft(db, draft.id)


def test_mock_mode_never_calls_gmail(db, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_ADDRESS", "yunaki.demo@example.com")
    monkeypatch.setenv("LIVE_MODE", "false")
    recorder = _SendRecorder()
    sender = build_gmail_sender(service=recorder)

    draft = _approved_draft(db)
    result = execute_draft(db, draft.id, sender)

    assert result["mocked"] is True
    assert recorder.sent == []  # the callable was never invoked
    assert db.execute("SELECT COUNT(*) c FROM outbox").fetchone()["c"] == 1


def test_live_mode_sends_the_approved_draft(db, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_ADDRESS", "yunaki.demo@example.com")
    monkeypatch.setenv("LIVE_MODE", "true")
    recorder = _SendRecorder()
    sender = build_gmail_sender(service=recorder)

    draft = _approved_draft(db)
    result = execute_draft(db, draft.id, sender)

    assert result["mocked"] is False
    assert len(recorder.sent) == 1
    mime = message_from_bytes(
        base64.urlsafe_b64decode(recorder.sent[0]["raw"].encode())
    )
    assert mime["To"] == "mei.lin.demo@example.com"
    assert mime["From"] == "yunaki.demo@example.com"
    assert mime["Subject"] == "Your documents"


def test_unapproved_draft_cannot_execute(db, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_ADDRESS", "yunaki.demo@example.com")
    monkeypatch.setenv("LIVE_MODE", "true")
    recorder = _SendRecorder()
    sender = build_gmail_sender(service=recorder)

    case_id = seed(db)
    draft = create_draft(
        db,
        DraftAction(
            case_id=case_id,
            kind="client_email",
            trigger="manual",
            to=DraftTo(name="Mei Lin", channel_address="mei.lin.demo@example.com"),
            body="never approved",
        ),
    )
    with pytest.raises(ValueError, match="approved"):
        execute_draft(db, draft.id, sender)
    assert recorder.sent == []
