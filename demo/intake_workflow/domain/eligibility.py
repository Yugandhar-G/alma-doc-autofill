"""Eligibility red-flag screening: route sensitive answers to the attorney.

FROZEN CONTRACT: signatures and docstrings are the interface; bodies are
implemented by the phase-3 domain agent.

Legal judgment stays human (design doc §2): automation may DETECT a red
flag and route it, but never interprets it, never surfaces it to the client,
and never blocks the client's normal flow. Findings produced here are
attorney-facing and live in Submission.internal_flags — the client portal
must never render them.
"""
from __future__ import annotations

from datetime import datetime

from intake_workflow.schemas import AutoCheckFinding, Case, ChecklistItem, TimelineEvent, utcnow
from intake_workflow.store import Store

# Question keys on the ben_eligibility section that trigger attorney review
# when answered "Yes", with the attorney-facing description used in findings.
RED_FLAG_KEYS: dict[str, str] = {
    "criminal_history": "Criminal history disclosed",
    "immigration_violations": "Immigration violation disclosed",
    "prior_denials": "Prior denial disclosed",
}

# The free-text field carrying the applicant's explanation for each red flag.
# Not a uniform suffix, so it is spelled out per key.
_DETAILS_KEYS: dict[str, str] = {
    "criminal_history": "criminal_details",
    "immigration_violations": "violation_details",
    "prior_denials": "denial_details",
}


def _now(now: datetime | None) -> datetime:
    return now or utcnow()


def screen_answers(
    item: ChecklistItem, answers: dict[str, str], now: datetime | None = None
) -> list[AutoCheckFinding]:
    """Return attorney-facing findings for red-flag answers.

    A finding per RED_FLAG_KEYS key answered "Yes" (case-insensitive),
    including the matching details answer verbatim when provided (e.g.
    criminal_details for criminal_history). Empty list when the item has no
    red-flag fields or nothing was flagged. Never raises."""
    answers = answers or {}
    field_keys = {f.key for f in getattr(item, "fields", []) or []}
    findings: list[AutoCheckFinding] = []
    for key, description in RED_FLAG_KEYS.items():
        # Ignore items that don't carry this red-flag field at all.
        if key not in field_keys:
            continue
        if (answers.get(key) or "").strip().lower() != "yes":
            continue
        details = (answers.get(_DETAILS_KEYS.get(key, "")) or "").strip()
        message = f"{description}: {details}" if details else description
        findings.append(AutoCheckFinding(code=key, message=message))
    return findings


def attorney_queue(store: Store) -> list[dict]:
    """Everything awaiting attorney review, oldest first::

        [{"case_id", "case_title", "item_key", "item_label",
          "flags": [finding messages], "since": datetime}]

    Sourced from items with attorney_review=True across all cases; ``since``
    is the flagged submission's submitted_at."""
    rows: list[dict] = []
    for case in store.list_cases():
        for item in case.items:
            if not item.attorney_review:
                continue
            flagged = [s for s in item.submissions if s.internal_flags]
            sub = flagged[-1] if flagged else (
                item.submissions[-1] if item.submissions else None
            )
            rows.append(
                {
                    "case_id": case.id,
                    "case_title": case.title,
                    "item_key": item.key,
                    "item_label": item.label,
                    "flags": [f.message for f in sub.internal_flags] if sub else [],
                    "since": sub.submitted_at if sub else case.created_at,
                }
            )
    rows.sort(key=lambda r: r["since"])
    return rows


def clear_attorney_review(
    store: Store, case: Case, item_key: str, *, reviewer: str, note: str = "",
    now: datetime | None = None,
) -> ChecklistItem:
    """Attorney signs off: set attorney_review=False, append a timeline event
    (kind ``attorney_cleared``, neutral summary + staff note in data), persist.
    KeyError for an unknown item_key; ValueError if the item is not currently
    under attorney review."""
    now = _now(now)
    item = next((i for i in case.items if i.key == item_key), None)
    if item is None:
        raise KeyError(item_key)
    if not item.attorney_review:
        raise ValueError(f"Item {item_key!r} is not under attorney review.")
    item.attorney_review = False
    store.add_timeline(
        TimelineEvent(
            case_id=case.id,
            ts=now,
            kind="attorney_cleared",
            summary=f"{reviewer} cleared background-question review on “{item.label}”",
            data={"item": item.key, "reviewer": reviewer, "note": note},
        )
    )
    store.save_case(case)
    return item
