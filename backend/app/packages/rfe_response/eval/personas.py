"""Offline RFE-response personas — synthetic RfeNotice fixtures paired with a
proposed (pre-audit) checklist, i.e. exactly what a model would hand back. The
eval runs the DETERMINISTIC path over them (deadline math + citation audit +
cover assembly); no LLM, so it runs in CI.

The bait persona is ``clean_notice``: its proposed checklist maps 1:1 to the
grounds with zero fabrications, so a run must produce ZERO defect labels. The
fabrication defect class is a checklist item that cites a ground the notice does
not contain and SURVIVES the audit ("survived_fabricated_ground"), or a null
deadline that gets a guessed day-count ("deadline_guessed"). Neither label is
ever expected, so if the audit or the deadline math regresses, it lands in the
harness's fabricated bucket and hard-fails.
"""
from dataclasses import dataclass, field

from app.packages.rfe_response.schemas import ChecklistItem, RfeGround, RfeNotice

# Fixed "today" for every persona so the day-counts are deterministic.
TODAY = "2026-01-01"


def _notice(grounds: list[RfeGround], deadline: str | None, form_id="I-129") -> RfeNotice:
    return RfeNotice(
        receipt_number="EAC0000000000",
        form_id=form_id,
        notice_date="2025-12-01",
        response_deadline=deadline,
        grounds=grounds,
    )


_G1 = RfeGround(ground_id="g1", quoted_text="The record does not establish sustained acclaim.",
                requested_evidence="Evidence of major awards or membership.")
_G2 = RfeGround(ground_id="g2", quoted_text="The beneficiary's role is not shown to be critical.",
                requested_evidence="Letters describing the critical role.")


@dataclass(frozen=True)
class RfePersona:
    name: str
    notice: RfeNotice
    raw_items: tuple[ChecklistItem, ...]
    today: str = TODAY
    matter_doc_ids: tuple[str, ...] = ()
    # The exact set of labels this run must produce — nothing more, nothing less.
    expected: frozenset[str] = frozenset()


PERSONAS: tuple[RfePersona, ...] = (
    # Fabrication bait: 1:1 checklist, valid refs, comfortable deadline.
    RfePersona(
        name="clean_notice",
        notice=_notice([_G1, _G2], deadline="2026-03-15"),  # 73 days out
        raw_items=(
            ChecklistItem(ground_id="g1", action="Gather award evidence", doc_kinds=["award"], refs=["g1"]),
            ChecklistItem(ground_id="g2", action="Obtain critical-role letters", doc_kinds=["recommendation_letter"], refs=["g2"]),
        ),
        expected=frozenset({"clean_map"}),
    ),
    # Fabricated ground: model proposes an item for a ground the notice lacks.
    # The audit MUST drop it (never survive).
    RfePersona(
        name="fabricated_ground",
        notice=_notice([_G1, _G2], deadline="2026-03-15"),
        raw_items=(
            ChecklistItem(ground_id="g1", action="Gather award evidence", doc_kinds=["award"], refs=["g1"]),
            ChecklistItem(ground_id="g2", action="Obtain letters", doc_kinds=["recommendation_letter"], refs=["g2"]),
            ChecklistItem(ground_id="g99", action="Respond to a ground that does not exist", doc_kinds=["other"], refs=["g99"]),
        ),
        expected=frozenset({"dropped_fabricated_ground"}),
    ),
    # Null-deadline honesty: no response-by date → unverifiable warning, never a
    # guessed day-count. Checklist itself is clean.
    RfePersona(
        name="null_deadline",
        notice=_notice([_G1], deadline=None),
        raw_items=(
            ChecklistItem(ground_id="g1", action="Gather award evidence", doc_kinds=["award"], refs=["g1"]),
        ),
        expected=frozenset({"clean_map", "deadline_unverifiable"}),
    ),
    # Past deadline: the window has closed → critical warning. Checklist clean.
    RfePersona(
        name="past_deadline",
        notice=_notice([_G1], deadline="2025-12-15"),  # 17 days before TODAY
        raw_items=(
            ChecklistItem(ground_id="g1", action="Gather award evidence", doc_kinds=["award"], refs=["g1"]),
        ),
        expected=frozenset({"clean_map", "deadline_critical"}),
    ),
    # Invented ref: a valid ground, but the item cites an id that is neither a
    # ground nor a matter doc → the audit strips it (correct behavior).
    RfePersona(
        name="invented_ref",
        notice=_notice([_G1], deadline="2026-03-15"),
        raw_items=(
            ChecklistItem(ground_id="g1", action="Gather award evidence", doc_kinds=["award"], refs=["g1", "ghost-doc-id"]),
        ),
        expected=frozenset({"stripped_ref"}),
    ),
)


def classify(expected: frozenset[str], actual: frozenset[str]) -> dict[str, list[str]]:
    """Compare expected vs actual label sets → classification buckets.

    correct    = label in both
    fabricated = label produced but not expected (the worst class — includes the
                 defect labels survived_fabricated_ground / deadline_guessed,
                 which no persona ever expects)
    missed     = label expected but not produced
    """
    return {
        "correct": sorted(expected & actual),
        "fabricated": sorted(actual - expected),
        "missed": sorted(expected - actual),
    }
