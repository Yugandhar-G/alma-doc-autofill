"""Email outbox: how drafted follow-ups become real messages.

FROZEN interface for phase 2 parallel work. GmailProvider lives in
app/email/gmail.py (email agent's turf); this module must not grow domain
logic.
"""
from __future__ import annotations

import os
import uuid
from typing import Protocol


class EmailSendError(RuntimeError):
    """Raised by providers when a send fails; callers leave the event drafted."""


class EmailProvider(Protocol):
    name: str

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        """Send one plain-text email; return a provider message id.
        Raises EmailSendError on any failure."""
        ...


class ConsoleProvider:
    """Dev/demo provider: records the send locally, no network."""

    name = "console"

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        print(f"[outbox:console] -> {to_email}  {subject!r}  ({len(body)} chars)")
        return f"console-{uuid.uuid4().hex[:10]}"


def get_provider() -> EmailProvider | None:
    """Resolve the configured provider from YUNAKI_EMAIL_PROVIDER.

    In the merged workflow, drafts route to the firm's Slack-approved,
    LIVE_MODE-gated pipeline by default, so unset/"" -> SendgateProvider.
    The direct GmailProvider stays available ("gmail") but is discouraged.

    "console" -> ConsoleProvider; "gmail" -> GmailProvider.from_env() (sends
    through the attorney's real Gmail via OAuth); "none" -> None, meaning
    approvals record the send without emailing (record-only); unset/""/
    "sendgate" -> SendgateProvider.
    """
    kind = os.environ.get("YUNAKI_EMAIL_PROVIDER", "").strip().lower()
    if kind == "none":
        return None
    if kind == "console":
        return ConsoleProvider()
    if kind == "gmail":
        from intake_workflow.email.gmail import GmailProvider

        return GmailProvider.from_env()
    # Default (unset/""/"sendgate"): the firm's Slack-approved outbound pipeline.
    from intake_workflow.integration.sendgate_provider import SendgateProvider

    return SendgateProvider()
