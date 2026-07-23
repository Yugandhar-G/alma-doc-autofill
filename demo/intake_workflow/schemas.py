"""Frozen data contracts for the Yunaki intake platform (Yew Legal prototype).

This file is the interface between the domain, storage, and web layers.
It is FROZEN for parallel work: implementation agents must not alter models,
fields, or enums — report a deviation instead of editing.

Conventions: dates are ISO ``YYYY-MM-DD``; timestamps are timezone-aware UTC.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- enums

class PartyRole(str, Enum):
    petitioner = "petitioner"
    beneficiary = "beneficiary"


class ItemKind(str, Enum):
    document = "document"
    question_section = "question_section"


class ItemState(str, Enum):
    """Checklist item lifecycle. Only ``accepted`` feeds form auto-population."""
    pending = "pending"
    submitted = "submitted"
    flagged = "flagged"      # auto-check found an issue; awaiting paralegal review
    checked = "checked"      # auto-check passed; awaiting paralegal review
    returned = "returned"    # paralegal sent back with a reason; client must resubmit
    accepted = "accepted"


class CaseStage(str, Enum):
    """Computed, never stored. Precedence: complete > ready_for_review > stalled
    > in_progress > opened > sent."""
    sent = "sent"
    opened = "opened"
    in_progress = "in_progress"
    stalled = "stalled"
    ready_for_review = "ready_for_review"
    complete = "complete"


class CheckStatus(str, Enum):
    passed = "passed"
    flagged = "flagged"


class Rung(str, Enum):
    """Escalation ladder rungs (default days: 3 / 7 / 12 / 18)."""
    nudge = "nudge"
    specifics = "specifics"
    call_offer = "call_offer"
    escalate = "escalate"    # internal task + drafted personal note for the attorney
    status_update = "status_update"  # post-filing client notification; not part of the ladder


class OutreachStatus(str, Enum):
    drafted = "drafted"      # sits in the approval queue; nothing auto-sends
    sent = "sent"
    dismissed = "dismissed"


# --------------------------------------------------------------------------- template models

class QuestionField(BaseModel):
    key: str
    label: str
    type: str = "text"          # text | date | select | textarea
    required: bool = True
    options: list[str] = Field(default_factory=list)   # for select
    pattern: str | None = None  # regex for inline validation (e.g. A-number)
    hint: str | None = None


class TemplateItem(BaseModel):
    key: str
    label: str
    description: str = ""
    kind: ItemKind = ItemKind.document
    assignee: PartyRole
    category: str | None = None   # bona fide evidence category, documents only
    required: bool = True
    fields: list[QuestionField] = Field(default_factory=list)


class CategoryRule(BaseModel):
    category: str
    label: str
    min_items: int = 1


class CaseTemplate(BaseModel):
    name: str
    label: str
    items: list[TemplateItem]
    categories: list[CategoryRule]
    min_categories: int = 3   # coverage met when >= this many categories are met


# --------------------------------------------------------------------------- case aggregate

class AutoCheckFinding(BaseModel):
    code: str      # machine-readable, e.g. "bad_extension", "could_not_verify"
    message: str   # plain language, safe to show the client


class AutoCheckResult(BaseModel):
    layer: int = 1
    status: CheckStatus
    findings: list[AutoCheckFinding] = Field(default_factory=list)
    checked_at: datetime


class Submission(BaseModel):
    id: str = Field(default_factory=new_id)
    submitted_at: datetime
    filename: str | None = None             # document submissions
    stored_path: str | None = None
    answers: dict[str, str] | None = None   # question_section submissions
    autocheck: AutoCheckResult | None = None
    # Attorney-only red-flag findings (eligibility screening). MUST never be
    # rendered in the client portal — the client sees the normal review flow.
    internal_flags: list[AutoCheckFinding] = Field(default_factory=list)


class ReviewAction(BaseModel):
    id: str = Field(default_factory=new_id)
    action: str                # "accepted" | "returned"
    reason: str | None = None  # required when returned; shown to the client verbatim
    reviewer: str
    at: datetime


class ChecklistItem(BaseModel):
    id: str = Field(default_factory=new_id)
    key: str
    label: str
    description: str = ""
    kind: ItemKind = ItemKind.document
    assignee: PartyRole
    category: str | None = None
    required: bool = True
    fields: list[QuestionField] = Field(default_factory=list)
    state: ItemState = ItemState.pending
    submissions: list[Submission] = Field(default_factory=list)
    reviews: list[ReviewAction] = Field(default_factory=list)
    # Red-flag answers route the item to the attorney; only staff clears it.
    # Automation (follow-ups, layer-2) must leave these items alone.
    attorney_review: bool = False

    @property
    def latest_return_reason(self) -> str | None:
        for review in reversed(self.reviews):
            if review.action == "returned":
                return review.reason
        return None

    @property
    def open(self) -> bool:
        """True while the client still owes something on this item."""
        return self.state in (ItemState.pending, ItemState.returned)


class Party(BaseModel):
    role: PartyRole
    full_name: str
    email: str
    token: str   # magic-link token; the client portal lives at /c/{token}
    last_activity_at: datetime | None = None


class LadderStep(BaseModel):
    day: int
    rung: Rung


def default_ladder() -> list[LadderStep]:
    return [
        LadderStep(day=3, rung=Rung.nudge),
        LadderStep(day=7, rung=Rung.specifics),
        LadderStep(day=12, rung=Rung.call_offer),
        LadderStep(day=18, rung=Rung.escalate),
    ]


class FollowUpPolicy(BaseModel):
    stall_days: int = 4   # firm-configurable 3-5; drives the `stalled` stage
    ladder: list[LadderStep] = Field(default_factory=default_ladder)
    # Trust ramp (phase 2): rungs listed here are sent automatically by the
    # scheduler when an email provider is configured. Escalate must never be
    # listed; the domain layer refuses to auto-send it regardless.
    auto_send_rungs: list[Rung] = Field(default_factory=list)


class OutreachEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    party_role: PartyRole
    rung: Rung
    subject: str
    body: str
    status: OutreachStatus = OutreachStatus.drafted
    created_at: datetime
    sent_at: datetime | None = None
    approved_by: str | None = None
    sent_via: str | None = None    # provider name ("console", "gmail"); None = recorded only
    message_id: str | None = None  # provider message id, for threading/audit


class Case(BaseModel):
    id: str = Field(default_factory=new_id)
    firm_id: str = "yew-legal"
    case_type: str = "marriage_aos"
    title: str
    consult_notes: str = ""
    created_at: datetime
    parties: list[Party]
    items: list[ChecklistItem]
    policy: FollowUpPolicy = Field(default_factory=FollowUpPolicy)
    outreach: list[OutreachEvent] = Field(default_factory=list)
    i485_approved_on: date | None = None   # unlocks I-751 date tracking
    filings: list[FilingRecord] = Field(default_factory=list)   # post-filing tracking

    def party(self, role: PartyRole) -> Party:
        return next(p for p in self.parties if p.role == role)

    def item(self, key: str) -> ChecklistItem:
        return next(i for i in self.items if i.key == key)


# --------------------------------------------------------------------------- post-filing

class Milestone(str, Enum):
    """USCIS case milestones, in typical order. ``rfe`` can occur out of band."""
    filed = "filed"
    receipt = "receipt"          # receipt notice arrived; clients can self-track
    biometrics = "biometrics"
    rfe = "rfe"                  # request for evidence
    interview = "interview"
    approved = "approved"
    denied = "denied"


class FilingUpdate(BaseModel):
    id: str = Field(default_factory=new_id)
    milestone: Milestone
    at: datetime
    note: str = ""   # staff-facing; the client-facing message is drafted separately


class FilingRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    form_type: str               # "I-130", "I-485", "I-765", "I-131", "I-751"
    filed_on: date
    receipt_number: str | None = None   # 3 letters + 10 digits, e.g. IOE0123456789
    status: Milestone = Milestone.filed
    updates: list[FilingUpdate] = Field(default_factory=list)


# --------------------------------------------------------------------------- derived / reporting

class I751Dates(BaseModel):
    gc_expires: date          # i485_approved_on + 2 years
    window_opens: date        # gc_expires - 90 days: earliest I-751 filing
    collect_docs_from: date   # window_opens - 30 days: start gathering evidence


class CategoryCoverage(BaseModel):
    category: str
    label: str
    accepted: int
    min_items: int
    met: bool


class CaseProgress(BaseModel):
    required_total: int
    accepted: int
    percent: int
    stage: CaseStage
    coverage: list[CategoryCoverage]
    coverage_met: bool


class TimelineEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    case_id: str
    ts: datetime
    kind: str      # e.g. case_created, item_submitted, item_returned, outreach_sent
    summary: str   # one line, lawyer-readable audit trail
    data: dict = Field(default_factory=dict)
