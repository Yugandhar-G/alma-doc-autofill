"""Config / env loader — CLAUDE_WORKPLAN.md §1.4 + §4.5.

Secrets only ever live in `.env` (gitignored day 0). Nothing here hardcodes a
token or a default for a secret. `load_dotenv` uses override=False, so an env
var set by the process (or a test monkeypatch) always wins over the file.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# §1.4 — the single set of config variables both workstreams share.
CONFIG_VARS: tuple[str, ...] = (
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_CHANNEL_CASES",
    "ANTHROPIC_API_KEY",
    "LIVE_MODE",
    "DB_PATH",
)

_DEFAULT_DB_PATH = "./yunaki.db"
_TRUTHY = {"1", "true", "yes", "on"}

# Load .env once at import. override=False keeps real env / test monkeypatch on top.
load_dotenv(override=False)


def get(name: str) -> str | None:
    """Read a config var by name. Returns None when unset."""
    if name not in CONFIG_VARS:
        raise KeyError(f"{name!r} is not a recognized config var; add it to §1.4 first")
    value = os.environ.get(name)
    return value if value not in (None, "") else None


def get_db_path() -> str:
    """DB_PATH from env, default ./yunaki.db."""
    return get("DB_PATH") or _DEFAULT_DB_PATH


def is_live_mode() -> bool:
    """LIVE_MODE gate (§4.1). Default False. Only explicit truthy values flip it."""
    raw = os.environ.get("LIVE_MODE", "false")
    return raw.strip().lower() in _TRUTHY
