"""PacketView — the session-scoped packet the check battery reads.

v0 the "packet" is just the extraction envelopes produced in one run request
(passport + G-28 today). ``gather_packet`` is the seam: the matter-scoped
upgrade will assemble a PacketView from a matter's stored documents instead of
one request's uploads, and the checks won't know the difference.
"""
from dataclasses import dataclass, field

from app.schemas import ExtractionEnvelope

# Doc types the extraction plane produces today → the USCIS form_id each maps
# to for the edition check. Passport is a travel document, not a USCIS form, so
# it has no form_id. New doc types extend this map.
_FORM_IDS: dict[str, str | None] = {
    "passport": None,
    "g28": "g-28",
}

_KNOWN_TYPES = frozenset(_FORM_IDS)


@dataclass(frozen=True)
class PacketDoc:
    """One document in the packet, flattened from its extraction envelope."""

    doc_type: str
    source_hash: str
    data: dict
    form_id: str | None = None


@dataclass(frozen=True)
class PacketView:
    """A packet of documents plus the case type driving the requirement checks.

    ``declared_editions`` maps form_id → the edition string that appears ON the
    packet's copy of that form. v0 extraction cannot read an edition marker, so
    the API always passes an empty map (the edition check stays dormant); tests
    and the offline eval supply synthetic editions to exercise it.
    """

    case_type: str
    docs: tuple[PacketDoc, ...]
    declared_editions: dict[str, str] = field(default_factory=dict)


def _doc_type_of(envelope: ExtractionEnvelope) -> str:
    """The document's effective type: the detected type when it is a concrete
    known type, else the requested slot type. A detected 'other'/'unknown'
    falls back to the slot so a wrong-doc-in-slot still counts as *that* slot's
    document being absent for completeness purposes."""
    detected = envelope.document_type_detected
    if detected in _KNOWN_TYPES:
        return detected
    return envelope.document_type_requested


def gather_packet(
    envelopes: list[ExtractionEnvelope],
    case_type: str,
    declared_editions: dict[str, str] | None = None,
) -> PacketView:
    """Build a PacketView from the run's extraction envelopes. THE SEAM: the
    matter-scoped upgrade replaces the envelope list with a matter document
    fetch and leaves every check untouched.

    Envelopes with no extracted data (a rejected slot) are dropped — there is
    nothing to cross-check against."""
    docs: list[PacketDoc] = []
    for env in envelopes:
        if env.data is None:
            continue
        doc_type = _doc_type_of(env)
        docs.append(
            PacketDoc(
                doc_type=doc_type,
                source_hash=env.source_hash or "",
                data=env.data,
                form_id=_FORM_IDS.get(doc_type),
            )
        )
    return PacketView(
        case_type=case_type,
        docs=tuple(docs),
        declared_editions=dict(declared_editions or {}),
    )
