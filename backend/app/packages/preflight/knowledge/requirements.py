"""Per-case-type required-document registry — v0 SEED DATA.

Structured so new case types plug in as data and so a requirement can later
carry a *condition* (e.g. "I-864 required only when the beneficiary is an
immediate relative"). v0 populates conditions with None (unconditionally
required); the field exists purely as the seam for that upgrade.

This is deliberately small and hand-seeded. It is NOT an authoritative USCIS
filing checklist — it encodes only what the current doc-type plane can
actually observe (passport + G-28). Expand it as new doc types land.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DocRequirement:
    """One required document for a case type. ``condition`` is the seam for
    conditional requirements; None means unconditionally required (v0)."""

    doc_type: str
    condition: str | None = None


@dataclass(frozen=True)
class CaseRequirements:
    case_type: str
    required: tuple[DocRequirement, ...]


# v0 seed: a G-28 filing minimally needs the beneficiary's passport and the
# signed G-28 itself. These are the only two doc types the extraction plane
# produces today, so they are the only ones we can honestly require.
_REQUIREMENTS: dict[str, CaseRequirements] = {
    "g28_filing": CaseRequirements(
        case_type="g28_filing",
        required=(
            DocRequirement(doc_type="passport"),
            DocRequirement(doc_type="g28"),
        ),
    ),
}


def requirements_for(case_type: str) -> CaseRequirements | None:
    """The requirements for a case type, or None when the type is unknown
    (an unknown case type yields no completeness findings — silence over a
    fabricated requirement)."""
    return _REQUIREMENTS.get(case_type)
