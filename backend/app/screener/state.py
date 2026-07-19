"""Graph state. Pydantic so every node write re-validates; the assessments
field carries an operator.add reducer for the per-criterion fan-in."""
import operator
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas import (
    CriterionAssessment,
    EvidenceDocRecord,
    EvidenceMatrix,
    FieldWarning,
    FinalMeritsAssessment,
    IntakeAnswers,
    ProfileSummary,
    ProfileVerification,
    ScreenerReport,
    VisaType,
    VisaVerdict,
    WebFinding,
)


class ScreenerState(BaseModel):
    session_id: str
    # True only for API-streamed runs: gates the thought-summary streaming
    # path so harness/test invokes never pay a speculative streaming call.
    live_feed: bool = False
    # Snapshotted from settings at run start (API layer): routing stays a pure
    # function of state — no node or edge ever reads live settings, which is
    # what makes per-tenant configuration possible without rebuilding graphs.
    web_enrichment_enabled: bool = False
    visa_targets: list[VisaType] = Field(default_factory=lambda: ["O1A", "EB1A"])
    intake: IntakeAnswers | None = None
    evidence_docs: list[EvidenceDocRecord] = Field(default_factory=list)
    matrix: EvidenceMatrix | None = None
    matrix_reviewed: bool = False
    web_findings: list[WebFinding] = Field(default_factory=list)
    grounded_urls: list[str] = Field(default_factory=list)
    verification: ProfileVerification | None = None
    profile_summary: ProfileSummary | None = None
    assessments: Annotated[list[CriterionAssessment], operator.add] = Field(
        default_factory=list
    )
    final_merits: FinalMeritsAssessment | None = None
    verdicts: list[VisaVerdict] = Field(default_factory=list)
    report: ScreenerReport | None = None
    warnings: Annotated[list[FieldWarning], operator.add] = Field(default_factory=list)


class AssessOneInput(BaseModel):
    """Payload carried by each Send() into the assess_one fan-out node."""

    criterion_id: str
    state: ScreenerState
