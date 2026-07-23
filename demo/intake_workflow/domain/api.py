"""Domain API for the Yunaki intake prototype.

FROZEN CONTRACT: signatures and docstrings below are the interface the web
layer is built against concurrently. Implement bodies without altering any
signature or docstring. If a contract looks defective, report it — do not
edit it. Private helpers go in sibling modules under app/domain/.

Conventions
-----------
- ``now`` defaults to None meaning ``schemas.utcnow()``; tests pass a fixed
  datetime for determinism.
- Functions that mutate a case persist it via ``store.save_case()`` and append
  a TimelineEvent for anything a lawyer would want on the case record.
- Null over guess: a check that cannot run (unreadable file, missing data)
  produces a flagged "could not verify" finding — never a silent pass, and
  never an exception escaping to the caller.
- The client portal for a party lives at ``/c/{party.token}``; absolute links
  in email bodies use ``http://localhost:8000`` in this prototype.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta

from intake_workflow.case_templates import get_template
from intake_workflow.domain import checks, eligibility, followups
from intake_workflow.schemas import (
    AutoCheckResult,
    CategoryCoverage,
    Case,
    CaseProgress,
    CaseStage,
    CheckStatus,
    ChecklistItem,
    I751Dates,
    ItemKind,
    ItemState,
    OutreachEvent,
    OutreachStatus,
    Party,
    PartyRole,
    ReviewAction,
    Rung,
    Submission,
    TimelineEvent,
    utcnow,
)
from intake_workflow.store import Store
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intake_workflow.email.outbox import EmailProvider


# --------------------------------------------------------------------------- helpers

def _now(now: datetime | None) -> datetime:
    return now or utcnow()


def _item(case: Case, item_key: str) -> ChecklistItem:
    """Lookup by key, raising KeyError for an unknown item (the submit contract)."""
    for item in case.items:
        if item.key == item_key:
            return item
    raise KeyError(item_key)


def _outreach(case: Case, outreach_id: str) -> OutreachEvent:
    """Lookup a drafted/sent outreach by id, raising KeyError if unknown."""
    for event in case.outreach:
        if event.id == outreach_id:
            return event
    raise KeyError(outreach_id)


def _timeline(store: Store, case: Case, now: datetime, kind: str, summary: str,
              data: dict | None = None) -> None:
    store.add_timeline(
        TimelineEvent(case_id=case.id, ts=now, kind=kind, summary=summary,
                      data=data or {})
    )


def create_case(
    store: Store,
    *,
    title: str,
    petitioner_name: str,
    petitioner_email: str,
    beneficiary_name: str,
    beneficiary_email: str,
    consult_notes: str = "",
    i485_approved_on: date | None = None,
    now: datetime | None = None,
) -> Case:
    """Instantiate the marriage_aos template into a new Case.

    - Every TemplateItem becomes a ChecklistItem in state ``pending``.
    - Each party gets a url-safe magic-link token (``secrets.token_urlsafe(16)``).
    - Appends a ``case_created`` timeline event; persists; returns the case.
    """
    now = _now(now)
    template = get_template("marriage_aos")
    items = [
        ChecklistItem(
            key=t.key,
            label=t.label,
            description=t.description,
            kind=t.kind,
            assignee=t.assignee,
            category=t.category,
            required=t.required,
            fields=[f.model_copy() for f in t.fields],
            state=ItemState.pending,
        )
        for t in template.items
    ]
    parties = [
        Party(
            role=PartyRole.petitioner,
            full_name=petitioner_name,
            email=petitioner_email,
            token=secrets.token_urlsafe(16),
        ),
        Party(
            role=PartyRole.beneficiary,
            full_name=beneficiary_name,
            email=beneficiary_email,
            token=secrets.token_urlsafe(16),
        ),
    ]
    case = Case(
        title=title,
        consult_notes=consult_notes,
        created_at=now,
        parties=parties,
        items=items,
        i485_approved_on=i485_approved_on,
    )
    store.save_case(case)
    _timeline(store, case, now, "case_created", f"Case created: {title}",
              {"case_type": case.case_type})
    return case


def record_activity(
    store: Store, case: Case, party_role: PartyRole, now: datetime | None = None
) -> Case:
    """Set the party's ``last_activity_at`` and persist. Called on every client
    portal visit and submission — this is what the stall detector reads."""
    now = _now(now)
    case.party(party_role).last_activity_at = now
    store.save_case(case)
    return case


def submit_answers(
    store: Store,
    case: Case,
    item_key: str,
    party_role: PartyRole,
    answers: dict[str, str],
    now: datetime | None = None,
) -> ChecklistItem:
    """Submit a question_section. Validates against the item's fields:
    required present and non-blank, pattern matches, date fields parseable
    ISO dates. Findings -> state ``flagged``; clean -> ``checked``. Appends
    the Submission (with AutoCheckResult), records activity, timeline event,
    persists. Raises KeyError for an unknown item_key."""
    now = _now(now)
    item = _item(case, item_key)
    result = checks.check_answers(item, answers, now)
    submission = Submission(submitted_at=now, answers=dict(answers), autocheck=result)
    item.submissions.append(submission)
    item.state = (
        ItemState.flagged if result.status == CheckStatus.flagged else ItemState.checked
    )
    case.party(party_role).last_activity_at = now
    _timeline(
        store, case, now, "item_submitted",
        f"{party_role.value} submitted “{item.label}” — {item.state.value}",
        {"item": item.key, "state": item.state.value, "role": party_role.value,
         "findings": [f.code for f in result.findings]},
    )

    # Eligibility red-flag screening runs alongside — never in place of — the
    # client-facing flow above. Findings are attorney-only: they route the item
    # to human review without touching item.state, the autocheck result, or
    # anything the portal renders.
    red_flags = eligibility.screen_answers(item, answers, now)
    if red_flags:
        submission.internal_flags = red_flags
        item.attorney_review = True
        _timeline(
            store, case, now, "attorney_review_flagged",
            "Background questions routed to attorney review",
            {"item": item.key, "codes": [f.code for f in red_flags]},
        )

    store.save_case(case)
    return item


def submit_document(
    store: Store,
    case: Case,
    item_key: str,
    party_role: PartyRole,
    filename: str,
    stored_path: str,
    now: datetime | None = None,
) -> ChecklistItem:
    """Submit a document upload. Runs ``layer1_check_file``; findings ->
    state ``flagged``; clean -> ``checked``. Appends the Submission, records
    activity, timeline event, persists. Raises KeyError for unknown item_key."""
    now = _now(now)
    item = _item(case, item_key)
    result = checks.check_file(stored_path, item, now)
    item.submissions.append(
        Submission(submitted_at=now, filename=filename, stored_path=stored_path,
                   autocheck=result)
    )
    item.state = (
        ItemState.flagged if result.status == CheckStatus.flagged else ItemState.checked
    )
    case.party(party_role).last_activity_at = now
    _timeline(
        store, case, now, "item_submitted",
        f"{party_role.value} uploaded “{item.label}” ({filename}) — {item.state.value}",
        {"item": item.key, "state": item.state.value, "filename": filename,
         "role": party_role.value,
         "findings": [f.code for f in result.findings]},
    )
    store.save_case(case)
    return item


def layer1_check_file(
    stored_path: str, item: ChecklistItem, now: datetime | None = None
) -> AutoCheckResult:
    """Deterministic layer-1 checks. Client-facing plain-language findings:

    - extension one of pdf/jpg/jpeg/png ("bad_extension")
    - size >= 20 KB ("too_small": scan may be blurry or incomplete)
      and <= 25 MB ("too_large")
    - PDFs open via pypdf with 1..100 pages ("unreadable_pdf" / "page_count")
    - images open via Pillow, min 600x600 px ("low_resolution")
    - anything unreadable/unexpected -> "could_not_verify" flag

    Never raises on hostile input — returns a flagged result instead."""
    return checks.check_file(stored_path, item, _now(now))


def review_item(
    store: Store,
    case: Case,
    item_key: str,
    *,
    action: str,
    reviewer: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> ChecklistItem:
    """Paralegal review. ``action`` is "accepted" or "returned"; returned
    requires a non-empty reason (ValueError otherwise — it is shown to the
    client verbatim). Appends ReviewAction, sets state, timeline, persists."""
    now = _now(now)
    if action not in ("accepted", "returned"):
        raise ValueError(f"Unknown review action: {action!r}")
    if action == "returned" and not (reason and reason.strip()):
        raise ValueError("A returned item requires a non-empty reason.")
    item = _item(case, item_key)
    item.reviews.append(
        ReviewAction(action=action, reason=reason, reviewer=reviewer, at=now)
    )
    if action == "accepted":
        item.state = ItemState.accepted
        _timeline(store, case, now, "item_accepted",
                  f"{reviewer} accepted “{item.label}”", {"item": item.key})
    else:
        item.state = ItemState.returned
        _timeline(store, case, now, "item_returned",
                  f"{reviewer} returned “{item.label}”: {reason.strip()}",
                  {"item": item.key, "reason": reason.strip()})
    store.save_case(case)
    if action == "accepted" and item.kind == ItemKind.question_section:
        try:  # bridge is optional and must never break the review flow
            from intake_workflow.integration import history_sync
            history_sync.sync_accepted_item(case, item)
        except Exception:
            import logging
            logging.getLogger("intake_workflow.integration").exception("history_sync failed")
    return item


def detect_stage(case: Case, now: datetime | None = None) -> CaseStage:
    """Computed case stage, precedence order:

    - complete: every required item accepted
    - ready_for_review: no required item pending/returned, but not complete
      (everything outstanding is in the paralegal's court)
    - stalled: some party with open required assigned items has been inactive
      >= policy.stall_days (base = last_activity_at or case.created_at)
    - in_progress: at least one submission exists on any item
    - opened: some party has activity but nothing submitted yet
    - sent: otherwise
    """
    now = _now(now)
    required = [i for i in case.items if i.required]

    # complete: every required item accepted
    if required and all(i.state == ItemState.accepted for i in required):
        return CaseStage.complete

    # ready_for_review: nothing outstanding on the client side (no required item
    # pending/returned), but not complete
    if not any(i.required and i.open for i in case.items):
        return CaseStage.ready_for_review

    # stalled: a party with open required assigned items has gone quiet
    for party in case.parties:
        open_assigned = [
            i for i in case.items
            if i.required and i.open and i.assignee == party.role
        ]
        if not open_assigned:
            continue
        base = party.last_activity_at or case.created_at
        if (now - base).days >= case.policy.stall_days:
            return CaseStage.stalled

    # in_progress: at least one submission on any item
    if any(i.submissions for i in case.items):
        return CaseStage.in_progress

    # opened: a party has visited but nothing submitted yet
    if any(p.last_activity_at is not None for p in case.parties):
        return CaseStage.opened

    return CaseStage.sent


def case_progress(case: Case, now: datetime | None = None) -> CaseProgress:
    """percent = accepted required items / total required items (int, 0-100).
    Coverage: per template CategoryRule, count *accepted* document items in
    that category; met when >= min_items. coverage_met when >= template
    min_categories categories are met. stage = detect_stage."""
    now = _now(now)
    template = get_template(case.case_type)

    required = [i for i in case.items if i.required]
    required_total = len(required)
    accepted = sum(1 for i in required if i.state == ItemState.accepted)
    percent = int(accepted * 100 / required_total) if required_total else 0

    coverage: list[CategoryCoverage] = []
    met_count = 0
    for rule in template.categories:
        count = sum(
            1 for i in case.items
            if i.category == rule.category
            and i.kind == ItemKind.document
            and i.state == ItemState.accepted
        )
        met = count >= rule.min_items
        if met:
            met_count += 1
        coverage.append(
            CategoryCoverage(
                category=rule.category, label=rule.label, accepted=count,
                min_items=rule.min_items, met=met,
            )
        )
    coverage_met = met_count >= template.min_categories

    return CaseProgress(
        required_total=required_total,
        accepted=accepted,
        percent=percent,
        stage=detect_stage(case, now),
        coverage=coverage,
        coverage_met=coverage_met,
    )


def draft_followup(
    case: Case, party_role: PartyRole, rung: Rung, now: datetime | None = None
) -> OutreachEvent:
    """Generate (do NOT persist) a follow-up drafted from live checklist state.

    Client rungs (nudge/specifics/call_offer): greet by first name; returned
    items with their reasons first, then pending items; mention thin bona fide
    categories when applicable; deep link http://localhost:8000/c/{token};
    warm, professional, concise; signed "Allison — Yew Legal". Escalating
    rungs get progressively more personal (call_offer offers a phone call).

    ``escalate`` rung: an internal note addressed to Allison summarizing the
    stall and drafting a personal outreach she can send herself.
    """
    now = _now(now)
    subject, body = followups.build(case, party_role, rung, now)
    return OutreachEvent(
        party_role=party_role, rung=rung, subject=subject, body=body,
        created_at=now,
    )


def run_scheduler(
    store: Store,
    now: datetime | None = None,
    provider: EmailProvider | None = None,
) -> list[OutreachEvent]:
    """One idempotent tick over all cases; returns newly created outreach.

    Follow-ups: for each party with open required assigned items:
      base = last_activity_at or case.created_at
      days = (now - base).days
      candidate = highest ladder step with step.day <= days
      draft only if no OutreachEvent for that (party, rung) was created after
      base (activity resets the ladder). Append to case.outreach as
      ``drafted``; timeline event; persist.

    Auto-send (phase 2): when ``provider`` is not None, a newly drafted event
    whose rung is in policy.auto_send_rungs is immediately sent via the
    provider (status ``sent``, approved_by "scheduler:auto", sent_via and
    message_id recorded, timeline event). ``escalate`` is never auto-sent
    regardless of configuration. EmailSendError leaves the event ``drafted``
    so it falls back to the approval queue — the tick never raises for a
    send failure.

    I-751: for cases with i485_approved_on, add one-time timeline alerts
    (kind ``i751_collect_docs`` / ``i751_window_open``) when now.date()
    passes collect_docs_from / window_opens; dedupe via existing timeline
    events of the same kind.
    """
    now = _now(now)
    today = now.date()
    drafted: list[OutreachEvent] = []

    for case in store.list_cases():
        case_changed = False

        # ---- escalation ladder follow-ups -------------------------------------
        for party in case.parties:
            open_required = [
                i for i in case.items
                if i.required and i.open and i.assignee == party.role
            ]
            if not open_required:
                continue

            base = party.last_activity_at or case.created_at
            days = (now - base).days

            candidate = None
            for step in sorted(case.policy.ladder, key=lambda s: s.day):
                if step.day <= days:
                    candidate = step
            if candidate is None:
                continue

            rung = candidate.rung
            already = any(
                o.party_role == party.role and o.rung == rung and o.created_at > base
                for o in case.outreach
            )
            if already:
                continue

            event = draft_followup(case, party.role, rung, now)
            case.outreach.append(event)
            drafted.append(event)
            case_changed = True
            _timeline(
                store, case, now, "outreach_drafted",
                f"Drafted {rung.value} follow-up for {party.full_name}",
                {"outreach_id": event.id, "rung": rung.value,
                 "party": party.role.value},
            )

            # Phase 2 auto-send: only when a provider is configured, the rung is
            # opted into policy.auto_send_rungs, and it is not the escalate rung
            # (an internal note that must never be auto-emailed to the client).
            # A send failure leaves the event drafted so it falls back to the
            # approval queue; the tick never raises for a send failure.
            if (provider is not None
                    and rung != Rung.escalate
                    and rung in case.policy.auto_send_rungs):
                from intake_workflow.email.outbox import EmailSendError

                try:
                    message_id = provider.send(
                        to_email=party.email, subject=event.subject,
                        body=event.body,
                    )
                except EmailSendError:
                    pass  # leave drafted; falls back to the approval queue
                else:
                    event.status = OutreachStatus.sent
                    event.sent_at = now
                    event.approved_by = "scheduler:auto"
                    event.sent_via = provider.name
                    event.message_id = message_id
                    _timeline(
                        store, case, now, "outreach_sent",
                        f"Auto-sent {rung.value} follow-up to {party.full_name}",
                        {"outreach_id": event.id, "rung": rung.value,
                         "party": party.role.value, "sent_via": provider.name},
                    )

        # ---- I-751 date alerts (second consumer of the scheduler) -------------
        if case.i485_approved_on is not None:
            dates = i751_dates(case.i485_approved_on)
            existing_kinds = {e.kind for e in store.list_timeline(case.id)}
            if (today >= dates.collect_docs_from
                    and "i751_collect_docs" not in existing_kinds):
                _timeline(
                    store, case, now, "i751_collect_docs",
                    f"I-751 evidence window: start gathering documents "
                    f"(green card expires {dates.gc_expires.isoformat()})",
                    {"collect_docs_from": dates.collect_docs_from.isoformat(),
                     "window_opens": dates.window_opens.isoformat(),
                     "gc_expires": dates.gc_expires.isoformat()},
                )
            if (today >= dates.window_opens
                    and "i751_window_open" not in existing_kinds):
                _timeline(
                    store, case, now, "i751_window_open",
                    f"I-751 filing window is open (green card expires "
                    f"{dates.gc_expires.isoformat()})",
                    {"window_opens": dates.window_opens.isoformat(),
                     "gc_expires": dates.gc_expires.isoformat()},
                )

        if case_changed:
            store.save_case(case)

    return drafted


def approve_outreach(
    store: Store, case: Case, outreach_id: str, approver: str,
    now: datetime | None = None,
    provider: EmailProvider | None = None,
) -> OutreachEvent:
    """Approval queue action: mark drafted -> sent, set sent_at/approved_by,
    timeline, persist. When ``provider`` is not None, actually send via it
    first (To: the party's email) and record sent_via/message_id; an
    EmailSendError leaves the event ``drafted`` and re-raises so the web
    layer can surface the failure. ``escalate`` events are internal notes —
    never emailed to the client even with a provider; they are recorded
    only. With no provider, the send is recorded only (phase 1 behavior).
    KeyError for unknown id; ValueError if not in drafted state."""
    now = _now(now)
    event = _outreach(case, outreach_id)
    if event.status != OutreachStatus.drafted:
        raise ValueError(f"Outreach {outreach_id} is {event.status.value}, not drafted.")

    # Phase 2: with a provider, actually email client-facing rungs before marking
    # the event sent. ``escalate`` is an internal note — recorded only, never
    # emailed to the client. A send failure leaves the event drafted (nothing has
    # been mutated yet) and re-raises so the web layer can surface it.
    if provider is not None and event.rung != Rung.escalate:
        party = case.party(event.party_role)
        message_id = provider.send(
            to_email=party.email, subject=event.subject, body=event.body
        )
        event.sent_via = provider.name
        event.message_id = message_id

    event.status = OutreachStatus.sent
    event.sent_at = now
    event.approved_by = approver
    _timeline(
        store, case, now, "outreach_sent",
        f"{approver} sent {event.rung.value} follow-up to {case.party(event.party_role).full_name}",
        {"outreach_id": event.id, "rung": event.rung.value},
    )
    store.save_case(case)
    return event


def dismiss_outreach(
    store: Store, case: Case, outreach_id: str, approver: str,
    now: datetime | None = None,
) -> OutreachEvent:
    """Approval queue action: mark drafted -> dismissed. Same error contract
    as approve_outreach."""
    now = _now(now)
    event = _outreach(case, outreach_id)
    if event.status != OutreachStatus.drafted:
        raise ValueError(f"Outreach {outreach_id} is {event.status.value}, not drafted.")
    event.status = OutreachStatus.dismissed
    event.approved_by = approver
    _timeline(
        store, case, now, "outreach_dismissed",
        f"{approver} dismissed {event.rung.value} follow-up for "
        f"{case.party(event.party_role).full_name}",
        {"outreach_id": event.id, "rung": event.rung.value},
    )
    store.save_case(case)
    return event


def i751_dates(i485_approved_on: date) -> I751Dates:
    """gc_expires = approval + 2 years (Feb 29 -> Feb 28); window_opens =
    gc_expires - 90 days; collect_docs_from = window_opens - 30 days."""
    try:
        gc_expires = i485_approved_on.replace(year=i485_approved_on.year + 2)
    except ValueError:
        # Feb 29 -> the +2y date doesn't exist; land on Feb 28.
        gc_expires = i485_approved_on.replace(year=i485_approved_on.year + 2, day=28)
    window_opens = gc_expires - timedelta(days=90)
    collect_docs_from = window_opens - timedelta(days=30)
    return I751Dates(
        gc_expires=gc_expires,
        window_opens=window_opens,
        collect_docs_from=collect_docs_from,
    )


def i751_radar(store: Store, now: datetime | None = None) -> list[dict]:
    """Staff-dashboard radar. For every case with i485_approved_on, a dict:
    {case_id, title, gc_expires, window_opens, collect_docs_from, status}
    where status is "window_open" (now >= window_opens), "collect_now"
    (now >= collect_docs_from), or "upcoming". Sorted soonest window first."""
    today = _now(now).date()
    radar: list[dict] = []
    for case in store.list_cases():
        if case.i485_approved_on is None:
            continue
        dates = i751_dates(case.i485_approved_on)
        if today >= dates.window_opens:
            status = "window_open"
        elif today >= dates.collect_docs_from:
            status = "collect_now"
        else:
            status = "upcoming"
        radar.append(
            {
                "case_id": case.id,
                "title": case.title,
                "gc_expires": dates.gc_expires,
                "window_opens": dates.window_opens,
                "collect_docs_from": dates.collect_docs_from,
                "status": status,
            }
        )
    radar.sort(key=lambda r: r["window_opens"])
    return radar
