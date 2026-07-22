"""Per-message events + draft store — kernel-free, core contracts only.

CLAUDE_WORKPLAN.md §2 / §4.4. This module takes the email agent's audited
EmailDecision and does exactly two things through /core: emit email.received
(always, FIRST), then — only when the decision carries an audited reply body —
create the pending DraftAction and emit draft.created. It never runs the agent
and never imports the kernel, so the event/ordering/masking guarantees are
testable on any interpreter.

NO PII IN THE EVENT PAYLOAD (§4.4): email.received carries {gmail_message_id,
from_hash, subject_len, category} — a sha256 of the sender address, a length, an
id, and a derived label. The raw address and body never enter an Event. (The
draft body holds the reply text, but a draft is human-gated + LIVE_MODE-gated,
not a log record.)

Draft kind: status_question → "status_reply"; every other drafting category →
"client_email". trigger is always "manual" (an inbound email is a manual,
human-facing trigger). A draft is created iff the decision has a reply body —
the audit downgrades a grounding violation to no reply body, so a violating
reply simply never becomes a draft.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from core import drafts
from core.events import emit
from core.models import DraftAction, DraftGrounding, DraftTo, Event
from gmail_agent import config
from gmail_agent.parsing import InboundEmail

logger = logging.getLogger("gmail_agent.pipeline")

_ACTOR = "agent:slack"  # Workstream A's actor id (this is the A email agent)
_STATUS_CATEGORY = "status_question"


@dataclass(frozen=True)
class EmailDecision:
    """The email agent's audited outcome for one inbound message."""

    category: str  # status_question|follow_up|new_client|other|no_action
    reply_subject: str | None
    reply_body: str | None  # None ⇒ no draft (no_action or audited-out)
    matched_case_id: str | None
    missing_items: list[str] = field(default_factory=list)
    case_state: dict[str, Any] = field(default_factory=dict)
    transcript_id: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    email_received_event_id: str
    category: str
    draft_id: str | None


def _from_hash(address: str | None) -> str:
    normalized = (address or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _draft_kind(category: str) -> str:
    return "status_reply" if category == _STATUS_CATEGORY else "client_email"


def process(
    conn: sqlite3.Connection, inbound: InboundEmail, decision: EmailDecision
) -> PipelineResult:
    """Emit email.received; create a draft + emit draft.created when the decision
    carries an audited reply body."""
    received = emit(
        conn,
        Event(
            type="email.received",
            case_id=decision.matched_case_id,
            actor=_ACTOR,
            payload={
                "gmail_message_id": inbound.gmail_message_id,
                "from_hash": _from_hash(inbound.from_address),
                "subject_len": len(inbound.subject or ""),
                "category": decision.category,
            },
        ),
    )

    if not decision.reply_body:
        logger.info(
            "message=%s category=%s → event only (no draft)",
            inbound.gmail_message_id,
            decision.category,
        )
        return PipelineResult(
            email_received_event_id=received.id,
            category=decision.category,
            draft_id=None,
        )

    kind = _draft_kind(decision.category)
    draft_case_id = decision.matched_case_id or config.UNMATCHED_CASE_ID
    days = int(decision.case_state.get("days_since_activity", 0) or 0)
    draft = DraftAction(
        case_id=draft_case_id,
        kind=kind,
        trigger="manual",
        to=DraftTo(
            name=inbound.from_name or inbound.from_address or "Unknown sender",
            channel_address=inbound.from_address or "",
        ),
        subject=decision.reply_subject,
        body=decision.reply_body,
        grounding=DraftGrounding(
            missing_items=list(decision.missing_items),
            case_state=dict(decision.case_state),
            days_since_activity=days,
        ),
    )
    created = drafts.create_draft(conn, draft)

    emit(
        conn,
        Event(
            type="draft.created",
            case_id=decision.matched_case_id,
            actor=_ACTOR,
            payload={
                "draft_id": created.id,
                "kind": created.kind,
                "channel": created.kind,
            },
        ),
    )
    logger.info(
        "message=%s category=%s → draft=%s kind=%s",
        inbound.gmail_message_id,
        decision.category,
        created.id,
        kind,
    )
    return PipelineResult(
        email_received_event_id=received.id,
        category=decision.category,
        draft_id=created.id,
    )
