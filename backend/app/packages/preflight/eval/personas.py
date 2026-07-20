"""Offline preflight personas — synthetic extraction-envelope sets with the
exact set of check_ids each packet must trigger.

No LLM anywhere (v0 has none), so these run in CI. The bait persona is
``clean_packet``: it must produce ZERO findings. A finding on a clean packet is
the fabrication defect class, which the harness hard-fails on.

The stale-edition persona relies on a SYNTHETIC form-edition registry (the
production one is intentionally empty); ``run.py`` installs it for the eval.
"""
from dataclasses import dataclass, field

from app.packages.preflight.knowledge.form_editions import FormEdition
from app.schemas import (
    BeneficiaryInfo,
    ExtractionEnvelope,
    G28Data,
    PassportData,
)

# Synthetic current-edition registry the offline eval installs over the (empty)
# production registry so form_edition_currency has something to compare against.
SYNTHETIC_REGISTRY: dict[str, FormEdition] = {
    "g-28": FormEdition(
        form_id="g-28",
        current_edition="05/31/24",
        source_url="https://example.test/uscis/g-28",  # synthetic; not authoritative
    ),
}


def _passport(source_hash: str, **fields) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="passport",
        document_type_detected="passport",
        data=PassportData(**fields).model_dump(),
        source_hash=source_hash,
    )


def _g28(source_hash: str, family_name=None, given_name=None) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="g28",
        document_type_detected="g28",
        data=G28Data(
            beneficiary=BeneficiaryInfo(family_name=family_name, given_name=given_name)
        ).model_dump(),
        source_hash=source_hash,
    )


@dataclass(frozen=True)
class PreflightPersona:
    name: str
    case_type: str
    envelopes: tuple[ExtractionEnvelope, ...]
    # form_id → edition string declared on the packet's copy of that form.
    declared_editions: dict[str, str] = field(default_factory=dict)
    # The exact set of check_ids this packet must fire — nothing more, nothing
    # less. Empty means a clean packet (zero findings).
    expected: frozenset[str] = frozenset()


PERSONAS: tuple[PreflightPersona, ...] = (
    # Fabrication bait: matching identity, both required docs, no stale edition.
    PreflightPersona(
        name="clean_packet",
        case_type="g28_filing",
        envelopes=(
            _passport("a" * 64, surname="GARCIA", given_names="MARIA", passport_number="X1234567"),
            _g28("b" * 64, family_name="Garcia", given_name="Maria"),
        ),
        expected=frozenset(),
    ),
    # Planted surname mismatch between passport and G-28 beneficiary.
    PreflightPersona(
        name="surname_mismatch",
        case_type="g28_filing",
        envelopes=(
            _passport("c" * 64, surname="GARCIA", given_names="MARIA"),
            _g28("d" * 64, family_name="SMITH", given_name="Maria"),
        ),
        expected=frozenset({"identity_consistency"}),
    ),
    # Missing required document: G-28 absent from a g28_filing packet.
    PreflightPersona(
        name="missing_required_doc",
        case_type="g28_filing",
        envelopes=(_passport("e" * 64, surname="NGUYEN", given_names="AN"),),
        expected=frozenset({"evidence_completeness"}),
    ),
    # Stale form edition (needs the synthetic registry). Identity matches and
    # both docs present, so ONLY the edition check fires.
    PreflightPersona(
        name="stale_edition",
        case_type="g28_filing",
        envelopes=(
            _passport("f" * 64, surname="OKAFOR", given_names="CHIDI"),
            _g28("0" * 64, family_name="Okafor", given_name="Chidi"),
        ),
        declared_editions={"g-28": "03/01/20"},
        expected=frozenset({"form_edition_currency"}),
    ),
    # Passport-number mismatch across two passport documents in one packet;
    # a G-28 with matching names keeps completeness and identity-name checks
    # clean, so ONLY the passport-number diff fires.
    PreflightPersona(
        name="passport_number_mismatch",
        case_type="g28_filing",
        envelopes=(
            _passport("1" * 64, surname="ROSSI", given_names="LUCA", passport_number="AA1111111"),
            _passport("2" * 64, surname="ROSSI", given_names="LUCA", passport_number="ZZ9999999"),
            _g28("3" * 64, family_name="Rossi", given_name="Luca"),
        ),
        expected=frozenset({"identity_consistency"}),
    ),
)


def classify(expected: frozenset[str], actual: frozenset[str]) -> dict[str, list[str]]:
    """Compare expected vs actual check_id sets → classification buckets.

    correct   = check_id in both
    fabricated = check_id fired but not expected (the worst class)
    missed    = check_id expected but did not fire
    """
    return {
        "correct": sorted(expected & actual),
        "fabricated": sorted(actual - expected),
        "missed": sorted(expected - actual),
    }
