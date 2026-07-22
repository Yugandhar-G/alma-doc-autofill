"""Offline fixtures for the agent tools — no network, no Gemini, no deepagents.

`run` executes a tool coroutine synchronously; `make_ctx` builds a minimal
kernel ToolContext (real AgentTranscript when importable, else a light stand-in)
so a ToolSpec's `run` closure can be dispatched directly in a test.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents import harness


@pytest.fixture()
def run():
    return lambda coro: asyncio.run(coro)


@pytest.fixture()
def make_ctx():
    """Return () -> (ctx, events) where events collects everything emit() saw."""

    def _make() -> tuple[Any, list[dict]]:
        from app.kernel.tools.registry import ToolContext

        events: list[dict] = []
        ctx = ToolContext(
            settings=_settings_or_stub(),
            transcript=harness.new_transcript(),
            emit=events.append,
            node="uscis",
        )
        return ctx, events

    return _make


def _settings_or_stub() -> Any:
    """Kernel Settings when constructible; the USCIS tool never reads it, so a
    bare object is fine when the backend config can't instantiate offline."""
    try:
        from app.kernel.config import Settings

        return Settings()
    except Exception:  # noqa: BLE001
        return object()
