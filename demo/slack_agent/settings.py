"""Startup config for the Slack agent — CLAUDE_WORKPLAN.md §1.4 / §4.

Standalone process (not a web app): a missing token is a fatal, loud startup
error, never a silent degrade. Tokens/channel come from core.config's env only
(secrets in .env, never in code — §4.5). Refusing to start without
SLACK_CHANNEL_CASES is the §4 guardrail that keeps posts on the demo workspace.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import config

# The three env vars this process cannot run without (§1.4).
REQUIRED = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_CASES")


class MissingConfig(RuntimeError):
    """Raised when one or more required env vars are absent."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "Missing required Slack config: "
            + ", ".join(missing)
            + ". Set them in .env (see .env.example). Never hardcode tokens."
        )


@dataclass(frozen=True)
class Settings:
    bot_token: str
    app_token: str
    channel_cases: str


def load() -> Settings:
    """Read + validate config. Raises MissingConfig listing every absent var."""
    values = {name: config.get(name) for name in REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise MissingConfig(missing)
    return Settings(
        bot_token=values["SLACK_BOT_TOKEN"],
        app_token=values["SLACK_APP_TOKEN"],
        channel_cases=values["SLACK_CHANNEL_CASES"],
    )
