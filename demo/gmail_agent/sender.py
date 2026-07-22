"""The Gmail send callable — CLAUDE_WORKPLAN.md §2 (Jul 22 scope change) + §4.1.

CONTRACT: `build_gmail_sender()` returns a `Callable[[DraftAction], None]` that
the SLACK process passes to `core.sendgate.execute_draft` on approve. sendgate is
the single execution layer that owns the LIVE_MODE decision (§4.1): under
LIVE_MODE=false it NEVER invokes this callable (renders to the outbox); under
LIVE_MODE=true it calls it to perform the real send. THIS MODULE MUST NEVER CHECK
LIVE_MODE — that would be a second enforcement point. It only knows how to send.

build_gmail_sender() loads OAuth credentials eagerly and raises cleanly
(auth.TokenMissing) if the token is absent, so the Slack process can treat the
Gmail sender as a soft dependency (register it when auth is ready, skip it
otherwise). No PII in logs: draft ids + byte counts only (§4.4).

THREADING (user-specified, verified against the Gmail API users.messages.send
reference): a reply must land in the client's existing Gmail thread. Gmail
threads a sent message when BOTH hold: (1) the message resource carries the
original `threadId`, AND (2) the RFC 2822 `In-Reply-To`/`References` headers
reference the original message's `Message-ID` HEADER (the RFC Message-ID — a
DIFFERENT value from the Gmail API message id) and the Subject matches. We set
threadId on the send body and both headers from grounding.case_state
(gmail_thread_id + rfc_message_id, carried there by pipeline/email_agent).
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any, Callable

from core.models import DraftAction
from gmail_agent import auth, config

logger = logging.getLogger("gmail_agent.sender")

GmailSender = Callable[[DraftAction], None]


def build_mime_message(draft: DraftAction, from_address: str) -> EmailMessage:
    """Build the RFC 2822 reply message for a draft (pure, testable).

    To = draft.to.channel_address, Subject = draft.subject, body = draft.body.
    When grounding.case_state carries the original RFC Message-ID, sets both
    In-Reply-To and References so the reply threads (header half of threading).
    """
    message = EmailMessage()
    message["To"] = draft.to.channel_address
    message["From"] = from_address
    message["Subject"] = draft.subject or ""
    message.set_content(draft.body or "")

    rfc_message_id = draft.grounding.case_state.get("rfc_message_id")
    if rfc_message_id:
        message["In-Reply-To"] = rfc_message_id
        message["References"] = rfc_message_id
    return message


def _raw(message: EmailMessage) -> str:
    """URL-safe base64 of the MIME bytes, as users.messages.send expects."""
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def build_send_body(draft: DraftAction, from_address: str) -> dict[str, Any]:
    """The users.messages.send request body: raw MIME + threadId (when known).

    threadId is the resource-level half of Gmail threading; the In-Reply-To /
    References headers built into the MIME are the header half. Both together
    (plus a matching Subject) are what make the reply land in the client's thread.
    """
    body: dict[str, Any] = {"raw": _raw(build_mime_message(draft, from_address))}
    thread_id = draft.grounding.case_state.get("gmail_thread_id")
    if thread_id:
        body["threadId"] = thread_id
    return body


def build_gmail_sender(
    service: Any | None = None, from_address: str | None = None
) -> GmailSender:
    """Build the send callable. Raises auth.TokenMissing if OAuth is not set up.

    The Gmail service + the From address are resolved once here; the returned
    closure performs the send. NEVER checks LIVE_MODE (sendgate owns that).
    `service`/`from_address` are injection seams for tests; production callers
    pass nothing and get the OAuth-backed service.
    """
    from_address = from_address or config.require_address()
    service = service if service is not None else auth.build_service()

    def _send(draft: DraftAction) -> None:
        body = build_send_body(draft, from_address)
        result = (
            service.users()
            .messages()
            .send(userId=config.GMAIL_USER_ID, body=body)
            .execute()
        )
        logger.info(
            "gmail send executed: draft=%s message_id=%s threaded=%s",
            draft.id,
            result.get("id", "?"),
            "threadId" in body,
        )

    return _send
