"""Pluggable sender registry — resolves the real-world send for a draft.kind.

Workstream A owns this. When Approve fires, approvals.approve resolves a sender
callable for the draft's kind through this registry and hands it to
core.sendgate.execute_draft — still the ONLY execution layer (§4.1). With
LIVE_MODE=false the callable is never invoked (sendgate mocks the send); with
LIVE_MODE=true sendgate calls it.

Default when no sender is registered for a kind: the caller passes a no-op
placeholder, exactly as before this registry existed. This is what lets the
gmail_agent (built in parallel, separate owner) be a SOFT dependency — main.py
tries to register its sender at startup and continues fine if it's absent.
"""

from __future__ import annotations

import logging
from typing import Callable

from core.models import DraftAction

logger = logging.getLogger("slack_agent.senders")

Sender = Callable[[DraftAction], None]

_REGISTRY: dict[str, Sender] = {}


def register_sender(kind: str, sender: Sender) -> None:
    _REGISTRY[kind] = sender
    logger.info("registered sender for kind=%s", kind)


def get_sender(kind: str) -> Sender | None:
    return _REGISTRY.get(kind)


def clear() -> None:
    """Drop all registered senders (test isolation / clean shutdown)."""
    _REGISTRY.clear()


def noop_sender(draft: DraftAction) -> None:
    """Placeholder used when no sender is registered for a kind.

    Only ever invoked under LIVE_MODE=true (sendgate mocks under false). Logs
    loud so a live send with no real channel wired is never silent.
    """
    logger.critical(
        "LIVE send requested for draft=%s kind=%s but no sender registered",
        draft.id,
        draft.kind,
    )
