"""Gmail API service factory — Workstream A (Jul 22 scope change, §1.4).

Credentials live ONLY in the .secrets/ paths named by env (§4.5):
  GMAIL_CREDENTIALS_PATH  OAuth client secret JSON (downloaded from GCP)
  GMAIL_TOKEN_PATH        minted user token (created by `python -m gmail_agent.client`)
  GMAIL_ADDRESS           the DEMO mailbox — never the firm's (§2 scope change)

`build_service()` is strict and loud: anything missing raises GmailNotConfigured
with the exact vars/paths at fault. Callers that can degrade (the mention
agent's read tools, main.py's soft sender registration) catch it and carry on;
nothing here ever silently no-ops.

Scopes are the minimum for the two jobs this package has: read the demo inbox
(agent tools) and send an APPROVED draft (sendgate-invoked sender, §4.1).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from core import config

logger = logging.getLogger("gmail_agent.client")

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)


class GmailNotConfigured(RuntimeError):
    """Gmail env/credentials absent — the caller decides whether to degrade."""


def _require_env(name: str) -> str:
    value = config.get(name)
    if not value:
        raise GmailNotConfigured(f"{name} unset in .env (see CLAUDE_WORKPLAN §1.4)")
    return value


def demo_address() -> str:
    """The demo mailbox address (raises if unset)."""
    return _require_env("GMAIL_ADDRESS")


def build_service() -> Any:
    """Build an authorized Gmail API service from the minted token.

    Refreshes an expired token in place; a missing/invalid token is a
    GmailNotConfigured (mint one with `python -m gmail_agent.client`).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = _require_env("GMAIL_TOKEN_PATH")
    if not os.path.exists(token_path):
        raise GmailNotConfigured(
            f"no Gmail token at {token_path} — run `python -m gmail_agent.client` "
            "once to authorize the demo mailbox"
        )
    creds = Credentials.from_authorized_user_file(token_path, list(SCOPES))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    if not creds.valid:
        raise GmailNotConfigured(
            f"Gmail token at {token_path} is invalid — re-run `python -m gmail_agent.client`"
        )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def authorize() -> None:
    """One-time interactive OAuth for the DEMO mailbox; writes the token file."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials_path = _require_env("GMAIL_CREDENTIALS_PATH")
    token_path = _require_env("GMAIL_TOKEN_PATH")
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, list(SCOPES))
    creds = flow.run_local_server(port=0)
    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    logger.info("gmail token written to %s", token_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    authorize()
