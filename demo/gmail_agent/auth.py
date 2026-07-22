"""OAuth installed-app flow + Gmail service builder — CLAUDE_WORKPLAN.md §1.4.

MINIMAL SCOPE SET (verified against the Gmail API reference, exactly what the
four operations this agent performs need — no more):

  https://www.googleapis.com/auth/gmail.readonly
      → users.watch, users.history.list, users.messages.get (format=full, i.e.
        headers + body). watch/history/get all accept the read scope; the
        narrower gmail.metadata scope is rejected here because it cannot return
        a message body, which triage needs.
  https://www.googleapis.com/auth/gmail.send
      → users.messages.send.

gmail.modify is deliberately NOT requested: this agent never changes labels,
marks read, trashes, or otherwise mutates a message, so the broader modify scope
would be unnecessary privilege. readonly + send is the least-privilege pair that
still supports watch + history.list + messages.get + messages.send.

CLI:  python -m gmail_agent.auth   → one-time browser consent, writes the token.

Google libraries are imported lazily inside functions so the rest of the package
(and its tests) import without google-auth-oauthlib present.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from gmail_agent import config

logger = logging.getLogger("gmail_agent.auth")

# The verified least-privilege scope set (see module docstring).
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)


class TokenMissing(RuntimeError):
    """Raised when no OAuth token exists yet (run the auth CLI first)."""


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_credentials() -> Any:
    """Load stored OAuth credentials, refreshing them if expired.

    Raises TokenMissing (clean, actionable) if the token file is absent — a send
    or a watch is impossible without prior consent. Fails loud, never silent.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = config.token_path()
    if not os.path.exists(token_path):
        raise TokenMissing(
            f"No OAuth token at {token_path!r}. Run `python -m gmail_agent.auth` "
            "once to grant consent (scopes: gmail.readonly + gmail.send)."
        )

    creds = Credentials.from_authorized_user_file(token_path, list(SCOPES))
    if creds.expired and creds.refresh_token:
        logger.info("refreshing expired Gmail OAuth token")
        creds.refresh(Request())
        _write_token(token_path, creds)
    if not creds.valid:
        raise TokenMissing(
            f"OAuth token at {token_path!r} is invalid and could not be "
            "refreshed. Re-run `python -m gmail_agent.auth`."
        )
    return creds


def _write_token(token_path: str, creds: Any) -> None:
    _ensure_parent_dir(token_path)
    with open(token_path, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    logger.info("wrote OAuth token to %s", token_path)


def build_service(credentials: Any | None = None) -> Any:
    """Build the Gmail API client from stored (or provided) credentials."""
    from googleapiclient.discovery import build

    creds = credentials if credentials is not None else load_credentials()
    # cache_discovery=False avoids a noisy warning + a file-cache dependency.
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def run_consent_flow() -> str:
    """Run the one-time installed-app browser consent and persist the token.

    Returns the token path written. Requires the OAuth client-secrets file at
    config.credentials_path() (a Desktop-app client downloaded from GCP).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials_path = config.credentials_path()
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"OAuth client secrets not found at {credentials_path!r}. Download a "
            "Desktop-app OAuth client from GCP into that path first "
            "(see docs/gmail-agent-setup.md)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, list(SCOPES))
    creds = flow.run_local_server(port=0)
    token_path = config.token_path()
    _write_token(token_path, creds)
    return token_path


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        token_path = run_consent_flow()
    except FileNotFoundError as exc:
        print(f"[gmail_agent.auth] STARTUP FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"[gmail_agent.auth] consent complete — token written to {token_path}.\n"
        "Scopes granted: gmail.readonly + gmail.send. "
        "Next: `python -m gmail_agent.watch`, then `python -m gmail_agent.main`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
