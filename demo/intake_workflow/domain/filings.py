"""Post-filing tracking: filings, USCIS milestones, client status notifications.

FROZEN CONTRACT: signatures and docstrings are the interface; bodies are
implemented by the phase-3 domain agent. The web layer builds against these.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from intake_workflow.schemas import (
    Case,
    FilingRecord,
    FilingUpdate,
    Milestone,
    OutreachEvent,
    PartyRole,
    Rung,
    TimelineEvent,
    utcnow,
)
from intake_workflow.store import Store

RECEIPT_RE = re.compile(r"^[A-Z]{3}\d{10}$")   # e.g. IOE0123456789

# Client-facing self-tracking page for receipt numbers.
USCIS_STATUS_URL = "https://egov.uscis.gov/casestatus/landing.do"

SIGNATURE = "Allison — Yew Legal"

# Warm, plain-language copy per milestone: (headline, what-happens-next).
# ``{form}`` is filled with the filing's form_type. No dates are ever promised.
_MILESTONE_COPY: dict[Milestone, tuple[str, str]] = {
    Milestone.filed: (
        "Your {form} petition has been filed with USCIS",
        "This is the official start of the process. USCIS will open a file for "
        "your case and, in the coming weeks, mail a receipt notice confirming "
        "they have everything.",
    ),
    Milestone.receipt: (
        "USCIS has issued a receipt notice for your {form}",
        "This confirms USCIS has your petition and has started working on it. "
        "The next step is usually a biometrics (fingerprint) appointment notice.",
    ),
    Milestone.biometrics: (
        "Your {form} case has reached the biometrics stage",
        "USCIS collects fingerprints and a photo to run their standard "
        "background checks. After this the case continues through review, and an "
        "interview notice may follow.",
    ),
    Milestone.rfe: (
        "USCIS has requested some additional evidence on your {form}",
        "This is a routine request for one or two more documents — it is not a "
        "denial. We will look at exactly what they are asking for and prepare a "
        "complete response together, well within their deadline.",
    ),
    Milestone.interview: (
        "Your {form} case has been scheduled for an interview",
        "This is usually the last major step. We will meet beforehand to prepare "
        "you fully, so you walk in knowing exactly what to expect.",
    ),
    Milestone.approved: (
        "Your {form} has been approved",
        "This is wonderful news. We will explain what the approval means for you "
        "and walk you through anything that comes next.",
    ),
    Milestone.denied: (
        "There has been a decision on your {form} case",
        "USCIS has issued a decision we need to talk through together. Please "
        "don't worry — we will review it carefully and go over your options.",
    ),
}


def _now(now: datetime | None) -> datetime:
    return now or utcnow()


def _normalize_receipt(receipt_number: str) -> str:
    """Upper-case/strip and validate against RECEIPT_RE. ValueError otherwise."""
    rn = (receipt_number or "").strip().upper()
    if not RECEIPT_RE.match(rn):
        raise ValueError(
            "That receipt number doesn't look right. A USCIS receipt number is "
            "three letters followed by 10 digits, for example IOE0123456789."
        )
    return rn


def _filing(case: Case, filing_id: str) -> FilingRecord:
    for record in case.filings:
        if record.id == filing_id:
            return record
    raise KeyError(filing_id)


def _timeline(store: Store, case: Case, now: datetime, kind: str, summary: str,
              data: dict | None = None) -> None:
    store.add_timeline(
        TimelineEvent(case_id=case.id, ts=now, kind=kind, summary=summary,
                      data=data or {})
    )


def _first_name(full_name: str) -> str:
    parts = (full_name or "").strip().split()
    return parts[0] if parts else full_name


def _status_update_copy(
    record: FilingRecord, milestone: Milestone, beneficiary_name: str
) -> tuple[str, str]:
    """Build ``(subject, body)`` for a client status notification. No dates."""
    first = _first_name(beneficiary_name)
    headline, explanation = _MILESTONE_COPY.get(
        milestone,
        ("There has been an update on your {form} case",
         "We wanted to let you know your case has moved forward."),
    )
    headline = headline.format(form=record.form_type)
    subject = f"An update on your {record.form_type} case — Yew Legal"

    parts = [f"Hi {first},", "", headline + ".", "", explanation]
    if record.receipt_number:
        parts += [
            "",
            f"Your USCIS receipt number is {record.receipt_number}. You can "
            f"check the latest status yourself anytime here:\n{USCIS_STATUS_URL}",
        ]
    parts += [
        "",
        "You don't need to do anything unless we reach out with a specific "
        "request — we're tracking this closely on our end.",
        "",
        "Warmly,",
        SIGNATURE,
    ]
    return subject, "\n".join(parts)


def record_filing(
    store: Store,
    case: Case,
    *,
    form_type: str,
    filed_on: date,
    receipt_number: str | None = None,
    now: datetime | None = None,
) -> FilingRecord:
    """Append a FilingRecord to the case (status ``filed`` plus an initial
    FilingUpdate), add a timeline event, persist, return the record.

    ``receipt_number``: when provided (it usually arrives later), must match
    RECEIPT_RE after upper-casing/stripping — ValueError otherwise, with a
    plain-language message. ``form_type`` is free text but normalized to
    upper-case ("i-130" -> "I-130")."""
    now = _now(now)
    form = form_type.strip().upper()
    rn = _normalize_receipt(receipt_number) if receipt_number else None
    record = FilingRecord(
        form_type=form,
        filed_on=filed_on,
        receipt_number=rn,
        status=Milestone.filed,
        updates=[FilingUpdate(milestone=Milestone.filed, at=now,
                              note="Filing recorded.")],
    )
    case.filings.append(record)
    _timeline(
        store, case, now, "filing_recorded",
        f"Recorded {form} filing" + (f" (receipt {rn})" if rn else ""),
        {"filing_id": record.id, "form_type": form, "receipt_number": rn,
         "filed_on": filed_on.isoformat()},
    )
    store.save_case(case)
    return record


def set_receipt_number(
    store: Store, case: Case, filing_id: str, receipt_number: str,
    now: datetime | None = None,
) -> FilingRecord:
    """Attach/replace the receipt number on an existing filing (validated as
    in record_filing); appends a ``receipt`` FilingUpdate and sets status to
    ``receipt`` if the filing is still at ``filed``. Timeline; persist.
    KeyError for an unknown filing_id."""
    now = _now(now)
    record = _filing(case, filing_id)          # KeyError for unknown filing_id
    rn = _normalize_receipt(receipt_number)    # validated before any mutation
    record.receipt_number = rn
    record.updates.append(
        FilingUpdate(milestone=Milestone.receipt, at=now,
                     note="Receipt notice recorded.")
    )
    if record.status == Milestone.filed:
        record.status = Milestone.receipt
    _timeline(
        store, case, now, "filing_receipt",
        f"Receipt number recorded for {record.form_type}: {rn}",
        {"filing_id": record.id, "receipt_number": rn,
         "status": record.status.value},
    )
    store.save_case(case)
    return record


def update_filing_status(
    store: Store,
    case: Case,
    filing_id: str,
    *,
    milestone: Milestone,
    note: str = "",
    now: datetime | None = None,
) -> FilingRecord:
    """Append a FilingUpdate, set the filing's status, timeline, persist.
    KeyError for an unknown filing_id. ``note`` is staff-facing."""
    now = _now(now)
    record = _filing(case, filing_id)          # KeyError for unknown filing_id
    record.updates.append(FilingUpdate(milestone=milestone, at=now, note=note))
    record.status = milestone
    _timeline(
        store, case, now, "filing_status",
        f"{record.form_type} status updated to {milestone.value}",
        {"filing_id": record.id, "status": milestone.value, "note": note},
    )
    store.save_case(case)
    return record


def draft_status_update(
    store: Store, case: Case, filing_id: str, now: datetime | None = None
) -> OutreachEvent:
    """Draft a client-facing notification for the filing's latest update and
    persist it into case.outreach (status ``drafted``, rung ``status_update``,
    addressed to the beneficiary) — it flows through the same approval queue
    and email provider as every other outreach.

    Body: warm, plain-language explanation of what the milestone means and
    what typically happens next; when a receipt_number exists, include it and
    the USCIS self-tracking link (USCIS_STATUS_URL). Never invent timeline
    promises — describe typical next steps, not dates. Signed
    "Allison — Yew Legal". Timeline event; KeyError for unknown filing_id."""
    now = _now(now)
    record = _filing(case, filing_id)          # KeyError for unknown filing_id
    beneficiary = case.party(PartyRole.beneficiary)
    latest = record.updates[-1] if record.updates else None
    milestone = latest.milestone if latest else record.status
    subject, body = _status_update_copy(record, milestone, beneficiary.full_name)
    event = OutreachEvent(
        party_role=PartyRole.beneficiary,
        rung=Rung.status_update,
        subject=subject,
        body=body,
        created_at=now,
    )
    case.outreach.append(event)
    _timeline(
        store, case, now, "status_update_drafted",
        f"Drafted {record.form_type} status update for {beneficiary.full_name}",
        {"outreach_id": event.id, "filing_id": record.id,
         "milestone": milestone.value},
    )
    store.save_case(case)
    return event
