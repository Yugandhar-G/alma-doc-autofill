"""Flat, Gemini-safe response schemas + checkpointed graph state for the
matter-intake agents.

Every model here that a node hands to Gemini as a ``response_schema`` is FLAT
(no discriminated unions, no maxItems on lists of nested models) and is listed
in tests/test_schema_lint.py — the same discipline the screener schemas follow.
Graph state models (ChaseState/PlannerState) are checkpointed by LangGraph, so
they carry only serializable primitives + the flat schemas above (never a store
handle or a TenantScope — those are reconstructed in-node from the firm ids the
state carries)."""
from pydantic import BaseModel, Field


# --- Chase: distillation + review contracts --------------------------------
class GapFinding(BaseModel):
    """One document gap the chase agent reasoned about.

    ``refs`` are matter doc_ids / memory ids the agent ACTUALLY opened (recorded
    in transcript.seen_refs). Empty refs are allowed only for a pure absence
    claim — a required doc_kind with zero matching documents, verified by CODE
    against the store, never trusted from the model."""

    rule_id: str | None = None
    doc_kind: str
    rationale: str
    refs: list[str] = Field(default_factory=list)


class GapFindings(BaseModel):
    findings: list[GapFinding] = Field(default_factory=list)


class ChaseDraft(BaseModel):
    """A drafted client message requesting one missing document. Nothing sends,
    ever — this is text for a human to review and send themselves."""

    doc_kind: str = ""
    language: str = "en"
    subject: str
    body: str


class ClassifiedArrival(BaseModel):
    """Pure-code classification of one already-attached document: its stored
    extraction's detected type vs the type it was filed under."""

    doc_id: str
    doc_type: str
    detected: str = "unknown"
    mismatch: bool = False


# --- Planner: distillation contract ----------------------------------------
class PlanStep(BaseModel):
    """One proposed next workflow. ``missing_inputs`` are inputs the step needs
    that the matter appears to lack — each subject to the same absence audit as
    a chase gap."""

    package_id: str
    reason: str
    missing_inputs: list[str] = Field(default_factory=list)


class ProposedPlan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)


# --- Ask-the-matter: distillation contract ---------------------------------
class ResearchAnswer(BaseModel):
    """An answer grounded strictly in firm data. ``refs`` are audited against
    the transcript; if every ref is stripped and the model did not mark the
    question unanswerable, the text is replaced with an honest
    cannot-substantiate message (the null-discipline analog)."""

    text: str
    refs: list[str] = Field(default_factory=list)
    unanswerable: bool = False


# --- Checkpointed graph state ----------------------------------------------
class ChaseState(BaseModel):
    """Chase graph state. firm_id/user_id reconstitute the TenantScope in-node
    (a store handle cannot be checkpointed); the shell sets them = the acting
    scope when it starts the run."""

    run_id: str = ""
    firm_id: str
    user_id: str
    matter_id: str
    case_type: str = "g28_filing"
    arrivals: list[ClassifiedArrival] = Field(default_factory=list)
    gaps: list[GapFinding] = Field(default_factory=list)
    drafts: list[ChaseDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report: dict | None = None


class PlannerState(BaseModel):
    """Planner graph state. ``matter_type`` gates which installed packages may
    be proposed (manifest.matter_types); ``case_type`` drives the requirements
    registry for the missing-input absence audit."""

    run_id: str = ""
    firm_id: str
    user_id: str
    matter_id: str
    matter_type: str = "immigration"
    case_type: str = "g28_filing"
    transcript_log: list[str] = Field(default_factory=list)
    seen_refs: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report: dict | None = None
