"""Preflight report contracts.

No LLM ever produces these — the whole package is pure code (v0 has zero
Gemini usage). They are still written flat and Gemini-safe (no discriminated
unions, no maxItems on model lists) and registered in the schema lint, so a
future doc-type plane that *does* ask a model to draft findings inherits a
response-schema that already satisfies Gemini's structured-output rules.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import SourceRef

Severity = Literal["critical", "warning", "info"]


class PreflightFinding(BaseModel):
    """One consistency defect the deterministic battery surfaced.

    Every factual claim in ``message`` must be reconstructible from the cited
    ``refs`` — a finding without support is the fabrication defect class this
    package guards against. ``refs`` may be empty for honest absence findings
    (a missing required document has no document to cite)."""

    check_id: str = Field(description="Name of the check that produced this finding")
    severity: Severity
    message: str
    refs: list[SourceRef] = Field(default_factory=list)


class PreflightReport(BaseModel):
    """The pre-filing audit result for one packet."""

    case_type: str
    findings: list[PreflightFinding] = Field(default_factory=list)
    checks_run: list[str] = Field(
        default_factory=list, description="Every check attempted, whether or not it fired"
    )
    docs_examined: int = 0
    ok: bool = Field(
        False, description="True when the packet has zero critical findings"
    )
