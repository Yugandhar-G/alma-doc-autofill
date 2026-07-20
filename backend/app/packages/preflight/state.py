"""Preflight graph state. Carries the extraction envelopes produced in one run
request (never raw bytes — envelopes reference documents by content hash) plus
the draft/final report. Checkpointed, so an in-review audit survives a reload."""
from pydantic import BaseModel, Field

from app.packages.preflight.schemas import PreflightReport
from app.schemas import ExtractionEnvelope


class PreflightState(BaseModel):
    run_id: str
    case_type: str = "g28_filing"
    # The packet: every extraction envelope this run produced. gather_packet
    # flattens these into a PacketView (the matter-scoped seam).
    envelopes: list[ExtractionEnvelope] = Field(default_factory=list)
    # Draft after cross_checks, then the human-approved final after finalize.
    report: PreflightReport | None = None
