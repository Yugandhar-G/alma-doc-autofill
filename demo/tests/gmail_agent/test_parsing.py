"""parsing — headers, from split, thread id, body extraction, bodyless → None."""

from __future__ import annotations

import base64

from gmail_agent import parsing


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_parse_message_extracts_fields():
    message = {
        "id": "m1",
        "threadId": "t1",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Ravi Kumar <ravi@demo.test>"},
                {"name": "Subject", "value": "Status?"},
                {"name": "Message-ID", "value": "<orig@mail.gmail.com>"},
            ],
            "body": {"data": _b64("Any update on my case?")},
        },
    }
    inbound = parsing.parse_message(message)
    assert inbound.gmail_message_id == "m1"
    assert inbound.gmail_thread_id == "t1"
    assert inbound.rfc_message_id == "<orig@mail.gmail.com>"
    assert inbound.from_name == "Ravi Kumar"
    assert inbound.from_address == "ravi@demo.test"
    assert inbound.subject == "Status?"
    assert inbound.body == "Any update on my case?"


def test_parse_message_prefers_plaintext_in_multipart():
    message = {
        "id": "m2",
        "threadId": "t2",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": "a@b.test"}],
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64("plain wins")}},
            ],
        },
    }
    inbound = parsing.parse_message(message)
    assert inbound.body == "plain wins"


def test_parse_message_no_body_is_none():
    message = {
        "id": "m3",
        "threadId": "t3",
        "payload": {"mimeType": "multipart/mixed", "headers": [], "parts": []},
    }
    inbound = parsing.parse_message(message)
    assert inbound.body is None


def test_header_value_case_insensitive():
    payload = {"headers": [{"name": "message-id", "value": "<x>"}]}
    assert parsing.header_value(payload, "Message-ID") == "<x>"
