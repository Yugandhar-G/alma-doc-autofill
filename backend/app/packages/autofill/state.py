"""Autofill graph state. Carries extraction envelopes and reviewed data —
never raw document bytes (state is checkpointed; documents live in the
DocumentStore, referenced by content hash inside each envelope)."""
from pydantic import BaseModel

from app.schemas import ExtractionEnvelope, G28Data, PassportData, PopulationReport


class AutofillState(BaseModel):
    run_id: str
    # What the extractor produced (post passport-merge, coherence warnings
    # attached) — the payload the reviewer sees at the interrupt.
    passport_envelope: ExtractionEnvelope | None = None
    g28_envelope: ExtractionEnvelope | None = None
    # What the human approved — re-validated through the same schemas as
    # extraction output; populate consumes ONLY these.
    passport: PassportData | None = None
    g28: G28Data | None = None
    headed: bool | None = None
    report: PopulationReport | None = None
