"""Gmail-agent config + the ONE constant block — CLAUDE_WORKPLAN.md §1.4 / §4.

Every address, project id, topic, subscription, path, label, model id, and
threshold this package uses is resolved here: either from the env (the §1.4
Gmail block) or from a module-level constant in this file. No literal address,
project id, topic, or model id appears anywhere else in the package (grep-clean).

The §1.4 Gmail vars are NOT part of core.config's CONFIG_VARS (that set is frozen
with /core), so they are read directly from os.environ here. `.env` is already
loaded by core.config at import time (load_dotenv, override=False), so importing
core.config keeps the demo's single-.env behaviour. Shared vars that DO live in
core.config (ANTHROPIC_API_KEY, LIVE_MODE, DB_PATH) are read through core.config
by the modules that need them — never re-declared here.

Startup validation: a missing required var raises MissingConfig naming every
absent var; entrypoints turn that into a clean message + non-zero exit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import core.config as _core_config  # noqa: F401  (import triggers load_dotenv)

# --------------------------------------------------------------------------- #
# Constant block — the only place literals live (§1.4 / no-hardcoding rule).
# --------------------------------------------------------------------------- #

# Env var names (the §1.4 Gmail block).
ENV_ADDRESS = "GMAIL_ADDRESS"
ENV_CREDENTIALS_PATH = "GMAIL_CREDENTIALS_PATH"
ENV_TOKEN_PATH = "GMAIL_TOKEN_PATH"
ENV_TOPIC = "GMAIL_TOPIC"
ENV_SUBSCRIPTION = "GMAIL_PUBSUB_SUBSCRIPTION"
ENV_ADC = "GOOGLE_APPLICATION_CREDENTIALS"

# Sensible defaults for the two secret PATHS (the secrets live under .secrets/,
# gitignored). Paths are config, not secrets, so a constant default is fine.
DEFAULT_CREDENTIALS_PATH = ".secrets/gmail_credentials.json"
DEFAULT_TOKEN_PATH = ".secrets/gmail_token.json"

# Gmail behaviour constants.
INBOX_LABEL = "INBOX"                     # watch + history are scoped to INBOX
HISTORY_TYPE = "messageAdded"             # only new-message history records
MESSAGE_FORMAT = "full"                   # need headers + body parts to triage
WATCH_RENEW_WITHIN_SECONDS = 24 * 60 * 60  # re-register within 24h of expiry
GMAIL_USER_ID = "me"                      # the authenticated mailbox

# Triage (Anthropic) constants — mirrors slack_agent.handoff_parser.
TRIAGE_MODEL_ID = "claude-haiku-4-5"
TRIAGE_MAX_TOKENS = 1024
TRIAGE_BODY_CHAR_CAP = 6000               # untrusted email body is capped here

# Synthetic case id for a draft whose sender matched no client row. draft.case_id
# is required by the frozen model; there is no FK on it (see core/db.py), so this
# marker lets replies to unknown senders still flow to Slack (which falls back to
# the #cases channel when a case has no thread mapping).
UNMATCHED_CASE_ID = "case_email_unmatched"

# The vars an entrypoint cannot run without. Paths are excluded (they default).
REQUIRED_ENV = (ENV_ADDRESS, ENV_TOPIC, ENV_SUBSCRIPTION, ENV_ADC)


class MissingConfig(RuntimeError):
    """Raised when one or more required Gmail env vars are absent."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "Missing required Gmail config: "
            + ", ".join(missing)
            + ". Set them in .env (see .env.example §1.4 Gmail block). "
            "Never hardcode tokens or addresses."
        )


@dataclass(frozen=True)
class GmailConfig:
    address: str
    credentials_path: str
    token_path: str
    topic: str
    subscription: str
    adc_path: str


def _env(name: str) -> str | None:
    """Read an env var, treating empty/whitespace-only as unset."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def credentials_path() -> str:
    """OAuth client-secrets path (env or the .secrets/ default constant)."""
    return _env(ENV_CREDENTIALS_PATH) or DEFAULT_CREDENTIALS_PATH


def token_path() -> str:
    """OAuth token path (env or the .secrets/ default constant)."""
    return _env(ENV_TOKEN_PATH) or DEFAULT_TOKEN_PATH


def require_address() -> str:
    """The demo mailbox address. Raises MissingConfig if unset."""
    address = _env(ENV_ADDRESS)
    if not address:
        raise MissingConfig([ENV_ADDRESS])
    return address


def load() -> GmailConfig:
    """Read + validate the full Gmail config. Raises MissingConfig listing every
    absent required var. Path vars fall back to their default constants."""
    values = {name: _env(name) for name in REQUIRED_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise MissingConfig(missing)
    return GmailConfig(
        address=values[ENV_ADDRESS],
        credentials_path=credentials_path(),
        token_path=token_path(),
        topic=values[ENV_TOPIC],
        subscription=values[ENV_SUBSCRIPTION],
        adc_path=values[ENV_ADC],
    )
