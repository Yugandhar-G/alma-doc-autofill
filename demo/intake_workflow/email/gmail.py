"""Gmail email provider: send through the attorney's real Gmail via OAuth.

The firm's spam-avoidance practice is to send follow-ups from the attorney's
own Gmail account rather than a generic transactional domain. This provider
implements the ``EmailProvider`` protocol (see app/email/outbox.py) on top of
the Gmail REST API using a long-lived OAuth refresh token.

No Google SDK is used — just ``httpx`` and the stdlib. Every failure (network,
non-2xx, malformed JSON, misconfiguration) is surfaced as ``EmailSendError``;
httpx exceptions never leak to callers.

Obtain the refresh token once with ``scripts/gmail_authorize.py`` (run by a
human) and supply the four ``GMAIL_*`` environment variables.
"""
from __future__ import annotations

import base64
import os
import time
from email.message import EmailMessage

import httpx

from intake_workflow.email.outbox import EmailSendError

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

# Refresh the cached access token when it is within this many seconds of expiry.
_EXPIRY_SKEW_SECONDS = 60.0
# Default lifetime to assume if the token endpoint omits ``expires_in``.
_DEFAULT_TOKEN_TTL_SECONDS = 3600.0

_REQUIRED_ENV = (
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "GMAIL_SENDER",
)


class GmailProvider:
    """Send plain-text email through a Gmail account via OAuth refresh token.

    Instances cache the OAuth access token in-process (with its expiry) so a
    scheduler tick sending several messages performs a single token exchange.
    """

    name = "gmail"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sender: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._sender = sender
        # ``transport`` is an injection seam for tests (httpx.MockTransport);
        # None means httpx uses its real network transport.
        self._transport = transport
        self._timeout = timeout
        self._access_token: str | None = None
        self._token_expiry: float = 0.0  # time.monotonic() deadline

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_env(cls) -> "GmailProvider":
        """Build a provider from the ``GMAIL_*`` environment variables.

        Raises ``EmailSendError`` naming every missing variable so a
        misconfigured deployment fails loudly instead of silently not sending.
        """
        missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise EmailSendError(
                "Gmail provider is not configured; missing environment "
                f"variable(s): {', '.join(missing)}"
            )
        return cls(
            client_id=os.environ["GMAIL_CLIENT_ID"],
            client_secret=os.environ["GMAIL_CLIENT_SECRET"],
            refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
            sender=os.environ["GMAIL_SENDER"],
        )

    # ------------------------------------------------------------------ public API

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        """Send one plain-text email; return the Gmail message id.

        Wraps token acquisition, MIME building, and the send call. Any failure
        becomes ``EmailSendError``.
        """
        token = self._access_token_value()
        raw = self._build_raw_message(to_email=to_email, subject=subject, body=body)
        payload = self._post_json(
            SEND_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
            what="Gmail send",
        )
        message_id = payload.get("id")
        if not message_id:
            raise EmailSendError(
                f"Gmail send response had no message id: {payload!r}"
            )
        return message_id

    # ------------------------------------------------------------------ internals

    def _access_token_value(self) -> str:
        """Return a cached access token, refreshing when absent or near expiry."""
        now = time.monotonic()
        if self._access_token is not None and now < self._token_expiry - _EXPIRY_SKEW_SECONDS:
            return self._access_token

        payload = self._post_json(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            what="Gmail token refresh",
        )
        token = payload.get("access_token")
        if not token:
            raise EmailSendError(
                f"Gmail token response had no access_token: {payload!r}"
            )
        try:
            ttl = float(payload.get("expires_in", _DEFAULT_TOKEN_TTL_SECONDS))
        except (TypeError, ValueError):
            ttl = _DEFAULT_TOKEN_TTL_SECONDS
        self._access_token = token
        self._token_expiry = time.monotonic() + ttl
        return token

    def _build_raw_message(self, *, to_email: str, subject: str, body: str) -> str:
        """Build a UTF-8 plain-text MIME message, urlsafe-base64 without padding."""
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body, subtype="plain", charset="utf-8")
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        # Gmail's API accepts urlsafe base64; strip padding to avoid any
        # ``=``-related quirks (the "no padding issues" contract).
        return encoded.rstrip("=")

    def _post_json(
        self,
        url: str,
        *,
        what: str,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> dict:
        """POST and return the parsed JSON body, wrapping every failure.

        Network errors, non-2xx responses, and unparseable bodies all raise
        ``EmailSendError`` — an httpx exception never escapes.
        """
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(url, headers=headers, data=data, json=json)
        except httpx.HTTPError as exc:  # network, timeout, connection, etc.
            raise EmailSendError(f"{what} request failed: {exc}") from exc

        if not response.is_success:
            body = response.text
            raise EmailSendError(
                f"{what} failed with HTTP {response.status_code}: {body[:500]}"
            )

        try:
            parsed = response.json()
        except ValueError as exc:  # includes json.JSONDecodeError
            raise EmailSendError(f"{what} returned invalid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise EmailSendError(
                f"{what} returned unexpected JSON type: {type(parsed).__name__}"
            )
        return parsed
