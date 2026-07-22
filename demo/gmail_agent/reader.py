"""Read-only Gmail access for the mention agent's tools.

Pure functions over an injected `service` (the googleapiclient object from
client.build_service, or a fake in tests) — blocking, so async callers wrap
them in asyncio.to_thread. Message bodies are UNTRUSTED external data (a
client's email can say anything, including instructions aimed at the model):
readers cap length here; the tool layer wraps the content in delimiters and
tells the model it is data, not instructions.

No PII in logs: message ids and counts only, never subjects/bodies (§4.4).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

logger = logging.getLogger("gmail_agent.reader")

MAX_BODY_CHARS = 4000
MAX_RESULTS_CAP = 10

_WANTED_HEADERS = ("From", "To", "Subject", "Date")


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for header in payload.get("headers", []):
        name = header.get("name", "")
        if name in _WANTED_HEADERS:
            out[name.lower()] = header.get("value", "")
    return out


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode(errors="replace")


def _plain_text(payload: dict[str, Any]) -> str:
    """Depth-first hunt for text/plain parts; falls back to empty string."""
    if payload.get("mimeType") == "text/plain":
        data = (payload.get("body") or {}).get("data")
        return _decode(data) if data else ""
    texts = [
        text
        for part in payload.get("parts") or []
        if (text := _plain_text(part))
    ]
    return "\n".join(texts)


def search_messages(
    service: Any, query: str, max_results: int = 5
) -> list[dict[str, str]]:
    """Search the demo mailbox; returns id/from/subject/date/snippet rows."""
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    rows: list[dict[str, str]] = []
    for ref in listing.get("messages") or []:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=ref["id"], format="metadata",
                 metadataHeaders=list(_WANTED_HEADERS))
            .execute()
        )
        rows.append(
            {
                "id": msg["id"],
                **_headers(msg.get("payload") or {}),
                "snippet": msg.get("snippet", ""),
            }
        )
    logger.info("gmail search: %d result(s)", len(rows))
    return rows


def get_message(service: Any, message_id: str) -> dict[str, str]:
    """Fetch one message: headers + plain-text body capped at MAX_BODY_CHARS."""
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = msg.get("payload") or {}
    body = _plain_text(payload) or msg.get("snippet", "")
    truncated = len(body) > MAX_BODY_CHARS
    if truncated:
        body = body[:MAX_BODY_CHARS]
    logger.info("gmail read: id=%s chars=%d truncated=%s", message_id, len(body), truncated)
    return {
        "id": msg.get("id", message_id),
        **_headers(payload),
        "body": body,
        "truncated": "true" if truncated else "false",
    }
