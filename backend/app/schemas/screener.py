"""Screener contracts: intake, evidence, criterion assessments, report.

Anti-fabrication contract (mirrors the extraction contract): every claim and
every verdict better than not_met must carry at least one SourceRef, and every
SourceRef is deterministically audited (screener/citations.py) against what
the user actually provided. A claim without a verifiable source is a defect;
"insufficient evidence" is a correct answer.

SourceRef is deliberately flat (kind + ref) rather than a discriminated union:
these models double as Gemini response_schema inputs, and flat models survive
the Pydantic→OpenAPI schema conversion reliably.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import FieldWarning

VisaType = Literal["O1A", "EB1A", "NIW"]
CriterionVerdict = Literal["met", "likely", "weak", "not_met"]

DISCLAIMER = (
    "This screener is decision support, not a legal determination. It does not "
    "constitute legal advice, does not create an attorney-client relationship, "
    "and must be reviewed by a licensed immigration attorney before any filing "
    "decision. USCIS adjudication outcomes depend on the full evidentiary "
    "record and adjudicator discretion."
)

EVIDENCE_KINDS = (
    "resume",
    "award",
    "press",
    "recommendation_letter",
    "publication",
    "salary_doc",
    "membership_proof",
    "patent",
    "other",
)
EvidenceKind = Literal[
    "resume",
    "award",
    "press",
    "recommendation_letter",
    "publication",
    "salary_doc",
    "membership_proof",
    "patent",
    "other",
]


class SourceRef(BaseModel):
    """One verifiable pointer at user-provided evidence.

    kind=answer → ref is an intake answer_id (e.g. "awards[0]")
    kind=doc    → ref is the SHA-256 of an uploaded document; excerpt must be a
                  verbatim quote from that document's extraction
    kind=web    → ref is a URL returned by grounded web enrichment
    kind=memory → ref is a firm-memory record id (MemoryRecord.id). Stays flat:
                  the memory id rides the existing `ref` field (no new field).
                  Valid iff the id was in the DETERMINISTIC set of memory records
                  actually recalled and shown to the model this run — an id
                  outside that set is the cross-firm/poisoned case and is stripped.
    """

    kind: Literal["answer", "doc", "web", "memory"]
    ref: str = Field(min_length=1, max_length=512)
    excerpt: str | None = Field(
        None,
        max_length=500,
        description="Verbatim quote backing the claim (required for kind=doc).",
    )


class IntakeAnswers(BaseModel):
    """Structured questionnaire. Field names double as stable answer_ids
    (list entries as name[index]); the citation audit resolves refs against
    exactly these ids. All fields optional — unanswered is a valid answer."""

    field_of_endeavor: str | None = Field(None, max_length=2000)
    current_role: str | None = Field(
        None, max_length=2000, description="Role, employer, and what the person actually does."
    )
    salary_context: str | None = Field(
        None,
        max_length=2000,
        description="Compensation and any comparator context (percentile, survey, geography).",
    )
    awards: list[str] = Field(
        default_factory=list, max_length=20, description="One award per entry, with year and scope."
    )
    memberships: list[str] = Field(default_factory=list, max_length=20)
    judging_activity: str | None = Field(
        None, max_length=2000, description="Peer review, program committees, competition judging."
    )
    publications_summary: str | None = Field(
        None, max_length=2000, description="Venues, counts, citation totals if known."
    )
    press_mentions: list[str] = Field(
        default_factory=list, max_length=20, description="Outlet + headline/date per entry."
    )
    original_contributions: str | None = Field(
        None, max_length=2000, description="What the person built/discovered and who adopted it."
    )
    critical_roles: str | None = Field(
        None, max_length=2000, description="Critical/essential roles at distinguished organizations."
    )
    exhibitions: str | None = Field(None, max_length=2000)
    commercial_success: str | None = Field(None, max_length=2000)
    one_time_major_award: str | None = Field(
        None,
        max_length=2000,
        description="Major internationally recognized award (Nobel-class), if any.",
    )


class EvidenceDocRecord(BaseModel):
    """One uploaded evidence document after extraction. Filename-free by
    design — documents are referenced by content hash only (PII log rule)."""

    source_hash: str
    document_kind_detected: EvidenceKind = "other"
    title: str | None = Field(None, max_length=300)
    key_facts: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="Verbatim excerpts (not paraphrases) — the citation audit substring-checks them.",
    )
    warnings: list[FieldWarning] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """One claim mapped to the criteria it could support. min_length=1 on
    sources means an uncited claim cannot even parse."""

    claim: str = Field(min_length=1, max_length=1000)
    criterion_ids: list[str] = Field(default_factory=list, max_length=10)
    # No max_length on sources: maxItems on a list of nested objects is the
    # documented Gemini response_schema 400 risk (see EvidenceMatrix.items);
    # compile._sanitize audits every source deterministically anyway.
    sources: list[SourceRef] = Field(min_length=1)


class EvidenceMatrix(BaseModel):
    # No max_length on items: Gemini rejects maxItems on an outer list of
    # nested objects (400 INVALID_ARGUMENT, verified 2026-07-15) and this
    # model doubles as a response_schema. The 100-item cap is enforced
    # deterministically in compile._sanitize instead.
    items: list[EvidenceItem] = Field(default_factory=list)
    unmapped_docs: list[str] = Field(
        default_factory=list, description="source_hashes with no criterion fit."
    )


class WebFinding(BaseModel):
    """One corroboration from grounded web search."""

    statement: str = Field(min_length=1, max_length=1000)
    url: str = Field(min_length=1, max_length=512)
    supports_criterion_ids: list[str] = Field(default_factory=list, max_length=10)


VerificationStatus = Literal["verified", "partially_verified", "unverified", "contradicted"]


class ClaimVerification(BaseModel):
    """The verification agent's judgment on one reviewed claim, backed by
    URLs it actually visited (enforced against the tool transcript)."""

    claim: str = Field(min_length=1, max_length=1000)
    status: VerificationStatus
    evidence_urls: list[str] = Field(default_factory=list)
    notes: str = Field("", max_length=1500, description="What was found or not found, specifically.")


class ProfileVerification(BaseModel):
    """Output of the tool-loop verification agent."""

    identity_confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence the online footprint belongs to this candidate, "
        "not a namesake."
    )
    verifications: list[ClaimVerification] = Field(default_factory=list)
    searched_but_absent: list[str] = Field(
        default_factory=list,
        description="Notable things that SHOULD be findable for a strong case "
        "but were not (a signal in itself).",
    )
    tool_calls_used: int = 0


class ProfileSummary(BaseModel):
    """User-facing synthesis: the profile as an adjudicator would see it."""

    headline: str = Field(min_length=1, max_length=300)
    strengths: list[str] = Field(default_factory=list, max_length=8)
    eligibility_drivers: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="What concretely makes this candidate eligible, tied to criteria.",
    )
    risks: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="What will draw an RFE or denial — the bounce-backs.",
    )
    verification_note: str = Field(
        "", max_length=1000,
        description="How the online verification affected this picture.",
    )


class CriterionAssessment(BaseModel):
    criterion_id: str
    verdict: CriterionVerdict
    reasoning: str = Field(min_length=1, max_length=4000)
    # No max_length (list of nested objects doubles as response_schema — see
    # EvidenceMatrix.items); the citation audit bounds what survives.
    citations: list[SourceRef] = Field(
        default_factory=list,
        description="Audited post-hoc; a verdict above not_met with zero valid citations is downgraded.",
    )
    gaps: list[str] = Field(default_factory=list, max_length=10)
    rfe_risks: list[str] = Field(default_factory=list, max_length=10)


class FinalMeritsAssessment(BaseModel):
    """Kazarian step 2 (EB-1A only): does the totality show sustained
    national/international acclaim and top-of-field standing?"""

    conclusion: Literal["favorable", "uncertain", "unfavorable"]
    reasoning: str = Field(min_length=1, max_length=4000)
    # No max_length: same response_schema constraint as EvidenceMatrix.items.
    citations: list[SourceRef] = Field(default_factory=list)


class VisaVerdict(BaseModel):
    visa: VisaType
    recommendation: Literal["strong", "possible", "weak", "not_recommended"]
    confidence: Literal["high", "medium", "low"]
    criteria_met: int = 0
    criteria_likely: int = 0
    summary: str = Field("", max_length=4000)
    next_steps: list[str] = Field(default_factory=list, max_length=10)


class ExhibitEntry(BaseModel):
    """One line in the draft exhibit index: a surviving (post-audit) piece of
    evidence, numbered and tied to the criterion it supports. Built by pure
    code from the audited matrix — never model-generated. Flat by design (it
    is walked by the schema-lint alongside the response-schema models).

    doc_ref carries the source document's sha256 only for kind=doc evidence;
    answer/web evidence is identified by source_kind + claim (no doc_ref)."""

    exhibit_no: str = Field(min_length=1, max_length=32)
    criterion_id: str = Field(min_length=1, max_length=64)
    claim: str = Field(min_length=1, max_length=1000)
    doc_ref: str | None = Field(
        None, max_length=128, description="Source document sha256 (kind=doc only)."
    )
    source_kind: Literal["answer", "doc", "web"]
    note: str = Field("", max_length=512)


class ExhibitIndex(BaseModel):
    """Draft exhibit map for attorney review: every surviving evidence source
    grouped and numbered per criterion, plus the applicable criteria that no
    surviving evidence covers. No max_length on entries — same response-schema
    constraint as EvidenceMatrix.items; the derivation bounds it deterministically."""

    entries: list[ExhibitEntry] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="Applicable criterion ids with zero supporting exhibit entries.",
    )


class ScreenerReport(BaseModel):
    session_id: str
    visa_targets: list[VisaType]
    profile_summary: ProfileSummary | None = None
    verification: ProfileVerification | None = None
    verdicts: list[VisaVerdict] = Field(default_factory=list)
    assessments: list[CriterionAssessment] = Field(default_factory=list)
    final_merits: FinalMeritsAssessment | None = None
    exhibit_index: ExhibitIndex | None = None
    warnings: list[FieldWarning] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER  # constant — never model-generated
