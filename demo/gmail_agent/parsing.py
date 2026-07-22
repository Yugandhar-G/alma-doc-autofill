"""Inbound Gmail message → structured InboundEmail — pure functions, no network.

A users.messages.get(format=full) response is a nested dict of MIME parts. These
helpers pull out exactly what triage + threading need and nothing else:

  - from name/address (email.utils.parseaddr)
  - subject
  - RFC 2822 Message-ID header (used later for In-Reply-To/References threading)
  - the plaintext body (text/plain preferred, else text/html), base64url-decoded

Body is returned as None when no text/plain or text/html part carries content —
the consumer skips bodyless messages. No PII is logged from here; callers derive
hashes/lengths for the event payload.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any


@dataclass(frozen=True)
class InboundEmail:
    gmail_message_id: str
    gmail_thread_id: str | None     # Gmail threadId, for get_email_thread
    rfc_message_id: str | None      # the Message-ID header, for threading
    from_name: str | None
    from_address: str | None
    subject: str | None
    body: str | None                # plaintext (or decoded HTML) body, or None


def _headers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload.get("headers") or []


def header_value(payload: dict[str, Any], name: str) -> str | None:
    """Case-insensitive lookup of a single header value; None if absent/blank."""
    target = name.lower()
    for header in _headers(payload):
        if str(header.get("name", "")).lower() == target:
            value = header.get("value")
            if isinstance(value, str):
                stripped = value.strip()
                return stripped or None
    return None


def _decode(data: str | None) -> str | None:
    if not data:
        return None
    # Gmail uses URL-safe base64 without padding guarantees.
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return None


def _collect_bodies(part: dict[str, Any], out: dict[str, str]) -> None:
    """Depth-first walk collecting the first non-empty text/plain and text/html."""
    mime_type = part.get("mimeType", "")
    body = part.get("body") or {}
    text = _decode(body.get("data"))
    if text and text.strip():
        if mime_type == "text/plain" and "text/plain" not in out:
            out["text/plain"] = text
        elif mime_type == "text/html" and "text/html" not in out:
            out["text/html"] = text
    for child in part.get("parts") or []:
        _collect_bodies(child, out)


def extract_body(payload: dict[str, Any]) -> str | None:
    """Prefer text/plain; fall back to text/html; None if neither has content."""
    found: dict[str, str] = {}
    _collect_bodies(payload, found)
    if "text/plain" in found:
        return found["text/plain"]
    if "text/html" in found:
        return found["text/html"]
    return None


def parse_message(message: dict[str, Any]) -> InboundEmail:
    """Turn a messages.get(format=full) response into an InboundEmail."""
    payload = message.get("payload") or {}
    from_header = header_value(payload, "From")
    from_name, from_address = ("", "")
    if from_header:
        from_name, from_address = parseaddr(from_header)
    thread_id = message.get("threadId")
    return InboundEmail(
        gmail_message_id=str(message.get("id", "")),
        gmail_thread_id=str(thread_id) if thread_id else None,
        rfc_message_id=header_value(payload, "Message-ID"),
        from_name=from_name or None,
        from_address=from_address or None,
        subject=header_value(payload, "Subject"),
        body=extract_body(payload),
    )
