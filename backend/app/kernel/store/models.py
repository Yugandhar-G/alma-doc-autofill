"""Matter-store domain models — the source of truth for the firm-scoped data
layer every C/D-tier workflow builds on. TS types mirror these.

Design notes:
- Ids are uuid4 hex strings minted by the store on create (callers never
  supply them); models below carry the id as a plain field because they
  describe rows that already exist.
- Timestamps are timezone-aware UTC (`datetime` with tzinfo). The store sets
  them; callers never pass created_at.
- `firm_id` is denormalized onto every child row (MatterDocument, WorkflowRun,
  RunArtifact, Interrupt, MemoryRecord) so the tenancy filter is a single
  indexed predicate at every read — a row can never be reached without its
  firm_id being matched first.
- Everything JSON-shaped (summary_json, payload_json, detail_json) is a dict;
  the store serializes it (TEXT in SQLite, jsonb in Supabase).
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

UserRole = Literal["attorney", "staff", "admin"]
MatterStatus = Literal["open", "closed"]
RunStatus = Literal["queued", "running", "awaiting_input", "done", "error"]
ArtifactKind = Literal["report", "population_pdf", "population_png", "transcript"]
InterruptStatus = Literal["pending", "resolved", "expired"]
MemoryKind = Literal["rfe", "denial", "approval", "review_edit", "outcome_note"]


class Firm(BaseModel):
    """A tenant. The root of every scope; all other rows hang off firm_id."""

    id: str
    name: str
    created_at: datetime


class User(BaseModel):
    """A member of a firm. auth_provider_id links to the external identity
    (Supabase Auth subject); None in local no-account mode."""

    id: str
    firm_id: str
    email: str
    role: UserRole
    auth_provider_id: str | None = None
    created_at: datetime


class Matter(BaseModel):
    """A case file. matter_type selects which workflow packages apply; title
    and client_ref are firm-facing labels (client_ref is PII — never logged)."""

    id: str
    firm_id: str
    matter_type: str
    title: str
    client_ref: str | None = None
    status: MatterStatus
    created_by: str
    created_at: datetime


class MatterDocument(BaseModel):
    """A document attached to a matter. doc_id is the existing content-hash
    from DocumentStore — the blob lives there, never duplicated here; this row
    is the matter-scoped index into it. filename is PII — never logged."""

    id: str
    matter_id: str
    firm_id: str
    doc_id: str
    doc_type: str
    filename: str
    uploaded_by: str
    created_at: datetime


class WorkflowRun(BaseModel):
    """One execution of a workflow package against a matter. thread_id is the
    checkpointer namespace (firm:matter:run); summary_json holds package-shaped
    result metadata; finished_at is None until the run terminates."""

    id: str
    matter_id: str
    firm_id: str
    package_id: str
    status: RunStatus
    thread_id: str
    started_by: str
    created_at: datetime
    finished_at: datetime | None = None
    summary_json: dict = Field(default_factory=dict)


class RunArtifact(BaseModel):
    """A durable output of a run (report, population PDF/PNG, transcript).
    artifact_ref points at where the bytes live (content hash or storage path);
    the store holds the pointer, not the payload."""

    id: str
    run_id: str
    firm_id: str
    kind: ArtifactKind
    artifact_ref: str
    created_at: datetime


class Interrupt(BaseModel):
    """A human-review checkpoint raised by a run's graph (a LangGraph
    `interrupt()` surfaced for firm action). node identifies the graph node;
    payload_json carries what the reviewer must see; status tracks resolution."""

    id: str
    run_id: str
    firm_id: str
    kind: str
    node: str
    payload_json: dict = Field(default_factory=dict)
    status: InterruptStatus
    created_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class MemoryRecord(BaseModel):
    """Firm memory — an outcome or edit worth recalling on future matters
    (RFE, denial, approval, review edit, outcome note). Schema lands now;
    writers arrive in D1. run_id/criterion_key are optional because not every
    memory originates in a run or attaches to a single criterion."""

    id: str
    firm_id: str
    matter_id: str
    run_id: str | None = None
    matter_type: str
    kind: MemoryKind
    criterion_key: str | None = None
    summary: str
    detail_json: dict = Field(default_factory=dict)
    created_at: datetime
