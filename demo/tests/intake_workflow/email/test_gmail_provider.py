"""GmailProvider unit tests — httpx.MockTransport, no network."""
from __future__ import annotations

import base64
import json
from email import message_from_bytes, policy
from email.header import decode_header, make_header

import httpx
import pytest

from intake_workflow.email.gmail import SEND_URL, TOKEN_URL, GmailProvider
from intake_workflow.email.outbox import EmailSendError


def _decode_raw(raw: str):
    """Reverse the provider's urlsafe-b64 (no padding) back to an email message."""
    padded = raw + "=" * (-len(raw) % 4)
    return message_from_bytes(base64.urlsafe_b64decode(padded), policy=policy.default)


def _header(msg, name: str) -> str:
    """Decode a possibly RFC 2047-encoded header back to its unicode value."""
    return str(make_header(decode_header(msg[name])))


def _make_provider(handler, **overrides):
    params = dict(
        client_id="cid",
        client_secret="secret",
        refresh_token="refresh-123",
        sender="attorney@example.com",
        transport=httpx.MockTransport(handler),
    )
    params.update(overrides)
    return GmailProvider(**params)


def test_happy_path_hits_both_endpoints_and_builds_utf8_mime():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TOKEN_URL:
            # The refresh-token grant carries the expected form fields.
            body = request.content.decode()
            assert "grant_type=refresh_token" in body
            assert "refresh_token=refresh-123" in body
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        if str(request.url) == SEND_URL:
            assert request.headers["Authorization"] == "Bearer tok-1"
            payload = json.loads(request.content)
            msg = _decode_raw(payload["raw"])
            assert _header(msg, "From") == "attorney@example.com"
            assert _header(msg, "To") == "client@example.com"
            assert _header(msg, "Subject") == "Föllow-up"
            assert "Hi Wei — please upload 📎" in msg.get_content()
            return httpx.Response(200, json={"id": "gmail-msg-1"})
        raise AssertionError(f"unexpected URL {request.url}")

    provider = _make_provider(handler)
    message_id = provider.send(
        to_email="client@example.com", subject="Föllow-up",
        body="Hi Wei — please upload 📎",
    )

    assert message_id == "gmail-msg-1"
    assert [str(r.url) for r in seen] == [TOKEN_URL, SEND_URL]


def test_access_token_is_cached_across_sends():
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if str(request.url) == TOKEN_URL:
            token_calls += 1
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"id": "id-x"})

    provider = _make_provider(handler)
    provider.send(to_email="a@example.com", subject="s", body="b")
    provider.send(to_email="c@example.com", subject="s", body="b")

    assert token_calls == 1  # second send reuses the cached, unexpired token


def test_send_non_2xx_raises_emailsenderror():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(500, text="upstream boom")

    provider = _make_provider(handler)
    with pytest.raises(EmailSendError) as exc:
        provider.send(to_email="a@example.com", subject="s", body="b")
    assert "500" in str(exc.value)


def test_token_non_2xx_raises_emailsenderror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    provider = _make_provider(handler)
    with pytest.raises(EmailSendError) as exc:
        provider.send(to_email="a@example.com", subject="s", body="b")
    assert "token refresh" in str(exc.value).lower()


def test_network_error_is_wrapped_not_leaked():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    provider = _make_provider(handler)
    with pytest.raises(EmailSendError):
        provider.send(to_email="a@example.com", subject="s", body="b")


def test_bad_json_from_token_endpoint_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    provider = _make_provider(handler)
    with pytest.raises(EmailSendError):
        provider.send(to_email="a@example.com", subject="s", body="b")


def test_send_response_missing_id_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"threadId": "t-1"})  # no "id"

    provider = _make_provider(handler)
    with pytest.raises(EmailSendError):
        provider.send(to_email="a@example.com", subject="s", body="b")


def test_from_env_reports_all_missing_variables(monkeypatch):
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                "GMAIL_REFRESH_TOKEN", "GMAIL_SENDER"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(EmailSendError) as exc:
        GmailProvider.from_env()
    message = str(exc.value)
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                "GMAIL_REFRESH_TOKEN", "GMAIL_SENDER"):
        assert var in message


def test_from_env_builds_provider_when_configured(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("GMAIL_SENDER", "attorney@example.com")
    provider = GmailProvider.from_env()
    assert provider.name == "gmail"
