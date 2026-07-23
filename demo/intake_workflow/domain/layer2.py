"""Layer-2 LLM validation: extraction + cross-document consistency checks.

FROZEN CONTRACT: signatures and docstrings are the interface; bodies are
implemented by the layer-2 agent, with helpers in app/domain/extractors.py.

Flag-only by design (PRINCIPLES §5): the LLM can never accept, reject, or
un-accept — it appends findings for the paralegal to weigh. Null over
guess: anything that cannot be verified yields a "could not verify" flag,
never a silent pass, and API errors never escape to callers.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Protocol

from intake_workflow.schemas import (
    AutoCheckFinding,
    AutoCheckResult,
    Case,
    CheckStatus,
    ChecklistItem,
    ItemKind,
    ItemState,
    TimelineEvent,
    utcnow,
)
from intake_workflow.store import Store


class Extractor(Protocol):
    """Extracts structured fields from a stored client document."""

    name: str

    def extract(self, stored_path: str, doc_hint: str) -> dict | None:
        """Return extracted fields for the document at ``stored_path``.

        ``doc_hint`` is the checklist item label (e.g. "Lease or deed with
        both names") so the extractor knows what the document should be.

        Expected keys (all optional; omit anything not literally present in
        the document — never guess): document_type (str), person_names
        (list[str]), issue_date / expiry_date (ISO YYYY-MM-DD str),
        address (str), notes (str).

        Returns None when the file cannot be read or extraction fails for
        any reason (including API errors) — null over guess.
        """
        ...


def get_extractor() -> Extractor | None:
    """Anthropic-backed extractor when ANTHROPIC_API_KEY is set; else None
    (the web layer shows a "no key configured" notice)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    # Imported lazily so the domain package doesn't require the anthropic
    # client (or a key) just to be imported for the deterministic layers.
    from intake_workflow.domain.extractors import AnthropicExtractor

    return AnthropicExtractor()


def run_layer2(
    store: Store, case: Case, extractor: Extractor, now: datetime | None = None
) -> list[ChecklistItem]:
    """Run layer-2 checks over this case's document items. Returns the items
    that were checked.

    Scope: document items whose latest submission has a stored file and whose
    state is ``checked`` or ``flagged``. Never touches ``accepted`` or
    ``returned`` items (a paralegal decision is never revisited by a machine)
    or question sections.

    For each item: extract fields via ``extractor``, then cross-check:
    - person names on the document vs both parties' full names and their
      biographic questionnaire answers (loose, case-insensitive matching)
    - expiry_date in the past -> flag ("this document appears expired")
    - the lease item must show BOTH spouses' names -> flag otherwise
    - extracted document_type inconsistent with the item -> flag
    - extraction returned None -> single "could not verify" flag

    Results append an AutoCheckResult(layer=2) to the latest submission with
    plain-language, client-safe findings. State rules (flag-only):
    - clean pass: state unchanged
    - findings on a ``checked`` item -> ``flagged``
    - findings on a ``flagged`` item -> stays ``flagged``
    Timeline event per item; persist the case once at the end.
    """
    now = now or utcnow()
    expected = _expected_names(case)
    checked: list[ChecklistItem] = []

    for item in case.items:
        # Documents only; a machine never revisits a paralegal decision.
        if item.kind != ItemKind.document:
            continue
        if item.state not in (ItemState.checked, ItemState.flagged):
            continue
        sub = item.submissions[-1] if item.submissions else None
        if sub is None or not sub.stored_path:
            continue

        findings = _cross_check(case, item, expected, extractor, now)
        result = AutoCheckResult(
            layer=2,
            status=CheckStatus.flagged if findings else CheckStatus.passed,
            findings=findings,
            checked_at=now,
        )
        # The submission carries a single autocheck slot; the layer-2 result
        # occupies it and its layer=2 marker lets staff tell the layers apart.
        sub.autocheck = result

        # Flag-only: findings push checked -> flagged (and keep flagged
        # flagged); a clean pass never changes state.
        if findings:
            item.state = ItemState.flagged

        store.add_timeline(
            TimelineEvent(
                case_id=case.id,
                ts=now,
                kind="layer2_checked",
                summary=f"AI cross-check on “{item.label}” — "
                f"{'flagged' if findings else 'passed'}",
                data={
                    "item": item.key,
                    "layer": 2,
                    "findings": [f.code for f in findings],
                },
            )
        )
        checked.append(item)

    store.save_case(case)
    return checked


# --------------------------------------------------------------- cross-check

def _expected_names(case: Case) -> list[str]:
    """Both parties' full names plus any biographic-questionnaire full_name
    answers — the set a document's names are expected to match against."""
    names = [p.full_name for p in case.parties if p.full_name]
    for key in ("pet_bio", "ben_bio"):
        item = next((i for i in case.items if i.key == key), None)
        if item and item.submissions:
            answers = item.submissions[-1].answers or {}
            full_name = (answers.get("full_name") or "").strip()
            if full_name:
                names.append(full_name)
    return names


def _cross_check(
    case: Case,
    item: ChecklistItem,
    expected: list[str],
    extractor: Extractor,
    now: datetime,
) -> list[AutoCheckFinding]:
    """Deterministic layer-2 checks over one document. Plain-language,
    client-safe findings (matching the tone of app.domain.checks)."""
    from intake_workflow.domain import extractors

    stored_path = item.submissions[-1].stored_path
    data = extractor.extract(stored_path, item.label)

    # Null over guess: no extraction -> a single "could not verify" flag,
    # never a silent pass.
    if data is None:
        return [
            AutoCheckFinding(
                code="could_not_verify",
                message="We couldn't automatically verify this document. "
                "A member of our team will take a look.",
            )
        ]

    findings: list[AutoCheckFinding] = []
    names = [n for n in (data.get("person_names") or []) if n]

    # Name consistency: only flag when the document names *someone* and none of
    # them plausibly match either spouse (a middle name never trips this).
    if names and not any(extractors.matches_any(n, expected) for n in names):
        findings.append(
            AutoCheckFinding(
                code="name_mismatch",
                message="The name on this document doesn't appear to match "
                "either spouse. Please double-check it was uploaded to the "
                "right case.",
            )
        )

    # The lease/deed must show BOTH spouses' names.
    if item.key == "lease":
        party_names = [p.full_name for p in case.parties if p.full_name]
        unmatched = [
            pn for pn in party_names
            if not any(extractors.names_match(n, pn) for n in names)
        ]
        if unmatched:
            findings.append(
                AutoCheckFinding(
                    code="missing_spouse_name",
                    message="A lease or deed should list both spouses' names, "
                    "but we could only confirm one. Please make sure both "
                    "names appear on the document.",
                )
            )

    # Expiry in the past.
    expiry = data.get("expiry_date")
    if expiry:
        try:
            if date.fromisoformat(expiry) < now.date():
                findings.append(
                    AutoCheckFinding(
                        code="expired_document",
                        message="This document appears to be expired. Please "
                        "upload a current version if you have one.",
                    )
                )
        except ValueError:
            # An unparseable date can't prove expiry — don't guess a flag.
            pass

    # Document type looks like a different kind of document than we asked for.
    doc_type = data.get("document_type")
    if doc_type and extractors.document_type_mismatches(
        doc_type, item.label, item.description or "", item.category or ""
    ):
        findings.append(
            AutoCheckFinding(
                code="document_type_mismatch",
                message="This looks like it may be a different type of document "
                "than the one we asked for here. Please double-check the upload.",
            )
        )

    return findings
