"""sender — MIME To/Subject/threading headers + threadId; raises without token."""

from __future__ import annotations

import pytest

from core.models import DraftAction, DraftGrounding, DraftTo
from gmail_agent import auth, sender


def _draft(case_state: dict) -> DraftAction:
    return DraftAction(
        case_id="case_x",
        kind="status_reply",
        trigger="manual",
        to=DraftTo(name="Ravi", channel_address="ravi@demo.test"),
        subject="Re: your case",
        body="Hi Ravi, here is the update.",
        grounding=DraftGrounding(case_state=case_state),
    )


def test_mime_sets_to_subject_and_threading_headers():
    draft = _draft({"rfc_message_id": "<orig@mail.gmail.com>", "gmail_thread_id": "t1"})
    message = sender.build_mime_message(draft, "agent.demo@example.com")
    assert message["To"] == "ravi@demo.test"
    assert message["Subject"] == "Re: your case"
    assert message["From"] == "agent.demo@example.com"
    assert message["In-Reply-To"] == "<orig@mail.gmail.com>"
    assert message["References"] == "<orig@mail.gmail.com>"


def test_send_body_sets_threadid_and_raw():
    draft = _draft({"rfc_message_id": "<orig@mail>", "gmail_thread_id": "t1"})
    body = sender.build_send_body(draft, "agent.demo@example.com")
    assert body["threadId"] == "t1"
    assert body["raw"]  # base64 MIME present


def test_send_body_no_threadid_when_absent():
    draft = _draft({})  # no gmail_thread_id
    body = sender.build_send_body(draft, "agent.demo@example.com")
    assert "threadId" not in body


def test_build_gmail_sender_raises_without_token(monkeypatch):
    monkeypatch.setenv(sender.config.ENV_ADDRESS, "agent.demo@example.com")

    def _raise() -> None:
        raise auth.TokenMissing("no token")

    monkeypatch.setattr(sender.auth, "build_service", _raise)
    with pytest.raises(auth.TokenMissing):
        sender.build_gmail_sender()
