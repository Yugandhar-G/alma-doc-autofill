"""The deterministic pre-flight check battery.

Every check is a pure function ``(packet: PacketView) -> list[PreflightFinding]``
registered in ``CHECKS``. No LLM anywhere — v0 is pure code. The contract that
matters: a packet with no real issue yields ZERO findings. Inventing a finding
is this package's fabrication defect class, so each check stays silent unless it
can cite the exact evidence (both sides of a mismatch, a registered edition, a
concrete requirement) from the packet it was handed.
"""
import unicodedata
from typing import Callable

from app.kernel.audit.refs import normalize
from app.packages.preflight.knowledge import form_editions
from app.packages.preflight.knowledge.poverty_guidelines import threshold
from app.packages.preflight.knowledge.requirements import requirements_for
from app.packages.preflight.packet import PacketDoc, PacketView
from app.packages.preflight.schemas import PreflightFinding
from app.schemas import SourceRef

Check = Callable[[PacketView], list[PreflightFinding]]


# --- identity consistency -------------------------------------------------- #

# Canonical identity keys → human label. Each doc type contributes a subset;
# the check compares a key only across docs that both carry it.
_IDENTITY_LABELS: dict[str, str] = {
    "surname": "surname",
    "given_names": "given name(s)",
    "middle_names": "middle name(s)",
    "date_of_birth": "date of birth",
    "nationality": "nationality",
    "passport_number": "passport number",
    "sex": "sex",
}


def _passport_identity(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in (
        "surname",
        "given_names",
        "middle_names",
        "date_of_birth",
        "nationality",
        "passport_number",
        "sex",
    ):
        value = data.get(key)
        if value:
            out[key] = str(value)
    return out


def _g28_identity(data: dict) -> dict[str, str]:
    beneficiary = data.get("beneficiary") or {}
    out: dict[str, str] = {}
    for key, src in (
        ("surname", "family_name"),
        ("given_names", "given_name"),
        ("middle_names", "middle_name"),
    ):
        value = beneficiary.get(src)
        if value:
            out[key] = str(value)
    return out


# doc_type → identity-claim extractor. New doc types register here; the diff
# machinery below is entirely doc-type-agnostic.
_IDENTITY_EXTRACTORS: dict[str, Callable[[dict], dict[str, str]]] = {
    "passport": _passport_identity,
    "g28": _g28_identity,
}


def _fold(text: str) -> str:
    """Whitespace-collapsed, lowercased, diacritics stripped — the canonical
    form for equality comparison. Generalizes the coherence check's casefold
    approach so 'José' and 'Jose' are the same person, but 'Garcia' and 'Smith'
    are not. Deterministic: equal-after-fold means no finding."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return normalize(without_marks)


def _identity_claims(doc: PacketDoc) -> dict[str, str]:
    extractor = _IDENTITY_EXTRACTORS.get(doc.doc_type)
    return extractor(doc.data) if extractor else {}


def identity_consistency(packet: PacketView) -> list[PreflightFinding]:
    """Every shared identity field, diffed across every ordered doc pair.

    Fields null on either side are skipped (a null is a valid extraction, not a
    mismatch). A difference that survives fold-normalization cites both
    documents with their differing verbatim values."""
    findings: list[PreflightFinding] = []
    claims = [(doc, _identity_claims(doc)) for doc in packet.docs]
    for i in range(len(claims)):
        doc_a, claims_a = claims[i]
        for j in range(i + 1, len(claims)):
            doc_b, claims_b = claims[j]
            for key in claims_a.keys() & claims_b.keys():
                value_a, value_b = claims_a[key], claims_b[key]
                if _fold(value_a) == _fold(value_b):
                    continue
                label = _IDENTITY_LABELS.get(key, key)
                findings.append(
                    PreflightFinding(
                        check_id="identity_consistency",
                        severity="critical",
                        message=(
                            f"{label} differs between the {doc_a.doc_type} "
                            f"('{value_a}') and the {doc_b.doc_type} "
                            f"('{value_b}'). Verify both documents describe the "
                            "same person before filing."
                        ),
                        refs=[
                            SourceRef(kind="doc", ref=doc_a.source_hash, excerpt=value_a),
                            SourceRef(kind="doc", ref=doc_b.source_hash, excerpt=value_b),
                        ],
                    )
                )
    return findings


# --- evidence completeness ------------------------------------------------- #


def evidence_completeness(packet: PacketView) -> list[PreflightFinding]:
    """Required doc types (from the requirements registry) vs doc types
    present. Each missing document is one finding. Absence findings honestly
    carry no refs — there is no document to cite for a document that isn't
    there (refs=[] is the truthful shape)."""
    requirements = requirements_for(packet.case_type)
    if requirements is None:
        return []  # unknown case type → no fabricated requirements
    present = {doc.doc_type for doc in packet.docs}
    findings: list[PreflightFinding] = []
    for requirement in requirements.required:
        if requirement.doc_type in present:
            continue
        findings.append(
            PreflightFinding(
                check_id="evidence_completeness",
                severity="critical",
                message=(
                    f"Required document '{requirement.doc_type}' is missing from "
                    f"the packet for case type '{packet.case_type}'. Filing "
                    "without it invites a rejection or RFE."
                ),
                refs=[],
            )
        )
    return findings


# --- form edition currency ------------------------------------------------- #


def form_edition_currency(packet: PacketView) -> list[PreflightFinding]:
    """Compare each form's declared edition against the registered current
    edition. Dormant in production: the registry is empty AND v0 extraction
    supplies no declared editions, so this returns []. It fires only when BOTH
    a declared edition and a registered current edition exist and they differ —
    a wrong-edition claim would be the fabrication class, so silence wins over a
    guess."""
    findings: list[PreflightFinding] = []
    for doc in packet.docs:
        if doc.form_id is None:
            continue
        declared = packet.declared_editions.get(doc.form_id)
        if not declared:
            continue  # can't read the edition → say nothing
        registered = form_editions.edition_for(doc.form_id)
        if registered is None:
            continue  # no verified current edition → say nothing
        if _fold(declared) == _fold(registered.current_edition):
            continue
        findings.append(
            PreflightFinding(
                check_id="form_edition_currency",
                severity="warning",
                message=(
                    f"Form {doc.form_id} in the packet is edition '{declared}', "
                    f"but the current USCIS edition is "
                    f"'{registered.current_edition}'. USCIS rejects superseded "
                    "editions; download the current form."
                ),
                refs=[SourceRef(kind="web", ref=registered.source_url)],
            )
        )
    return findings


# --- I-864 sufficiency (structure only, gated) ----------------------------- #


def income_sufficient(income: float, household_size: int, year: int) -> bool:
    """Is ``income`` at or above the I-864 125% guideline for the household?

    The reusable guideline math — fully implemented and unit-tested against the
    transcribed 2026 table even though the I-864/pay-stub doc types don't exist
    yet. Raises (via ``threshold``) on an untabulated year or sub-floor
    household rather than guessing."""
    return income >= threshold(year, household_size, "p125")


def i864_sufficiency(packet: PacketView) -> list[PreflightFinding]:
    """STRUCTURE ONLY. The I-864 affidavit-of-support income check needs
    I-864/pay-stub/tax-transcript extraction (future doc types); v0's plane
    produces neither an income figure nor a household size. Rather than pretend
    to check what extraction can't provide, this stays registered but returns
    no findings. When those doc types land, this reads them from the packet and
    calls ``income_sufficient`` above."""
    return []


CHECKS: tuple[Check, ...] = (
    identity_consistency,
    evidence_completeness,
    form_edition_currency,
    i864_sufficiency,
)


def run_checks(packet: PacketView) -> list[PreflightFinding]:
    """Run the whole battery in registration order; concatenate findings."""
    findings: list[PreflightFinding] = []
    for check in CHECKS:
        findings.extend(check(packet))
    return findings


def check_ids() -> list[str]:
    """The name of every registered check — the ``checks_run`` audit trail."""
    return [check.__name__ for check in CHECKS]
