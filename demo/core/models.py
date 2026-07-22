"""Frozen pydantic contracts — CLAUDE_WORKPLAN.md §1.1/§1.2/§1.3.

This module is the SINGLE source of truth for every closed enum in the system.
The event-type enum in particular lives here and nowhere else: adding a type is a
contract change (workplan §1.1), so `db.py`, `events.py`, and both workstreams
import these Literals / tuples rather than redeclaring string sets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, get_args
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Closed enums (source of truth). Tuples are derived from the Literals so the
# DDL CHECK constraints and pydantic validation can never drift apart.
# --------------------------------------------------------------------------- #

EventType = Literal[
    "case.handoff_received",   # A produces (parsed from Slack)
    "intake.sent",             # B produces
    "intake.client_activity",  # B produces (upload/edit/submit)
    "intake.validated",        # B produces — payload: {complete, missing[]}
    "draft.created",           # A or B produce — payload: {draft_id, kind, channel}
    "draft.approved",          # A produces (approval happens in Slack)
    "draft.rejected",          # A produces — payload: {reason}
    "message.sent",            # infra produces after approved draft executes
    "followup.due",            # B produces (timer fired)
    "escalation.raised",       # B produces → A must surface it in Slack
]
EVENT_TYPES: tuple[str, ...] = get_args(EventType)

DraftKind = Literal["client_email", "client_whatsapp", "slack_notification", "status_reply"]
DRAFT_KINDS: tuple[str, ...] = get_args(DraftKind)

DraftTrigger = Literal["validation_incomplete", "followup_timer", "escalation", "manual"]
DRAFT_TRIGGERS: tuple[str, ...] = get_args(DraftTrigger)

DraftState = Literal["pending", "approved", "rejected", "sent"]
DRAFT_STATES: tuple[str, ...] = get_args(DraftState)

PartyRole = Literal["petitioner", "beneficiary"]
PARTY_ROLES: tuple[str, ...] = get_args(PartyRole)

IntakeState = Literal["sent", "in_progress", "submitted", "accepted"]
INTAKE_STATES: tuple[str, ...] = get_args(IntakeState)

ChecklistState = Literal["missing", "uploaded", "accepted"]
CHECKLIST_STATES: tuple[str, ...] = get_args(ChecklistState)

# Documented actor prefixes (workplan §1.1). `client` is the one bare form.
_ACTOR_PREFIXES = ("agent:", "human:")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# §1.1 Event
# --------------------------------------------------------------------------- #

class Event(BaseModel):
    """Append-only event. `type` is validated against the closed enum."""

    id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    ts: str = Field(default_factory=_now_iso)
    type: EventType
    case_id: str | None = None
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("actor")
    @classmethod
    def _validate_actor(cls, value: str) -> str:
        if value == "client" or value.startswith(_ACTOR_PREFIXES):
            return value
        raise ValueError(
            "actor must be 'client', 'agent:<name>', or 'human:<name>' "
            f"(got {value!r})"
        )


# --------------------------------------------------------------------------- #
# §1.2 DraftAction — the only path to any outbound message
# --------------------------------------------------------------------------- #

class DraftTo(BaseModel):
    name: str
    channel_address: str


class DraftGrounding(BaseModel):
    missing_items: list[str] = Field(default_factory=list)
    case_state: dict[str, Any] = Field(default_factory=dict)
    days_since_activity: int = 0


class DraftAction(BaseModel):
    id: str = Field(default_factory=lambda: f"draft_{uuid4().hex}")
    case_id: str
    kind: DraftKind
    trigger: DraftTrigger
    to: DraftTo
    subject: str | None = None
    body: str
    grounding: DraftGrounding = Field(default_factory=DraftGrounding)
    state: DraftState = "pending"


# --------------------------------------------------------------------------- #
# §1.3 Minimal case model (shared read, B writes)
# --------------------------------------------------------------------------- #

class Case(BaseModel):
    id: str = Field(default_factory=lambda: f"case_{uuid4().hex}")
    name: str
    process_type: str
    stage: str
    created_at: str = Field(default_factory=_now_iso)


class Party(BaseModel):
    case_id: str
    client_id: str
    role: PartyRole


class Client(BaseModel):
    id: str = Field(default_factory=lambda: f"client_{uuid4().hex}")
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None


class Intake(BaseModel):
    id: str = Field(default_factory=lambda: f"intake_{uuid4().hex}")
    case_id: str
    client_id: str
    url: str
    state: IntakeState
    sent_at: str | None = None
    last_client_activity_at: str | None = None


class ChecklistItem(BaseModel):
    id: str = Field(default_factory=lambda: f"chk_{uuid4().hex}")
    intake_id: str
    seq: int
    label: str
    mandatory_to_file: bool = True
    state: ChecklistState = "missing"
