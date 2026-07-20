"""Per-case-type required-document registry — hand-seed + registry-derived.

Structured so new case types plug in as data and so a requirement can later
carry a *condition* (e.g. "I-864 required only when the beneficiary is an
immediate relative"). Conditions populate with None (unconditionally required);
the field exists purely as the seam for that upgrade.

Two sources feed ``requirements_for``:

  1. ``_REQUIREMENTS`` — a small hand-seeded map. It is NOT an authoritative
     USCIS checklist; it encodes only what the current doc-type plane can
     observe (passport + G-28). The seeded "g28_filing" entry is pinned by
     tests and stays unchanged.

  2. The visa→forms registry (``app.forms.registry.load_registry``), adapted
     into one CaseRequirements per visa classification. A seeded entry always
     wins over a derived one of the same case_type.

Derived-mapping rules (conservative — only mark "required" when the registry
data clearly says so; never invent requirement semantics):

  - case_type = the profile's ``visa_code`` lowercased (e.g. "H-1B" → "h-1b").
  - A form becomes a required doc ONLY when its ``role`` is one of
    {primary_petition, supplement, prerequisite} — the roles the reference
    plane treats as structurally part of (or a precondition for) the filing.
    optional / companion / beneficiary / attorney_rep forms are NOT required.
    A required form's ``doc_type`` is its ``form_id`` (e.g. "I-129").
  - A supporting document becomes a required doc ONLY when its ``required``
    flag is True. Its ``doc_type`` is the document's ``name`` verbatim.
  - No conditions are synthesized: every derived requirement is unconditional
    (condition=None). Nothing beyond form role and the required flag is read.
"""
from dataclasses import dataclass
from functools import lru_cache

from app.forms.registry import load_registry

# Form roles the reference plane treats as required parts of / preconditions for
# a filing. Everything else (optional, companion, beneficiary, attorney_rep) is
# excluded — a conservative reading that never over-requires.
_REQUIRED_FORM_ROLES: frozenset[str] = frozenset(
    {"primary_petition", "supplement", "prerequisite"}
)


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


@lru_cache(maxsize=1)
def _derived_requirements() -> dict[str, CaseRequirements]:
    """Build case-type requirement sets from the verified visa→forms registry.

    Keyed by ``visa_code`` lowercased. Required docs are the profile's forms
    whose role is in ``_REQUIRED_FORM_ROLES`` (doc_type = form_id) plus its
    supporting documents flagged required (doc_type = name). Raises via
    ``load_registry`` if the registry is missing or fails validation."""
    registry = load_registry()
    derived: dict[str, CaseRequirements] = {}
    for profile in registry.visas:
        reqs: list[DocRequirement] = []
        for form in profile.forms:
            if form.role in _REQUIRED_FORM_ROLES:
                reqs.append(DocRequirement(doc_type=form.form_id))
        for supporting in profile.supporting_documents:
            if supporting.required:
                reqs.append(DocRequirement(doc_type=supporting.name))
        case_type = profile.visa_code.lower()
        derived[case_type] = CaseRequirements(
            case_type=case_type, required=tuple(reqs)
        )
    return derived


def requirements_for(case_type: str) -> CaseRequirements | None:
    """The requirements for a case type, or None when the type is unknown
    (an unknown case type yields no completeness findings — silence over a
    fabricated requirement).

    Hand-seeded entries win over registry-derived ones of the same case_type."""
    seeded = _REQUIREMENTS.get(case_type)
    if seeded is not None:
        return seeded
    return _derived_requirements().get(case_type)
