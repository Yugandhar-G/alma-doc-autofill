"""Staff (paralegal / attorney) routes.

Contract with app/main.py: this module path and the ``router`` name are frozen.
All case logic goes through ``app.domain.api`` (imported as a module so tests can
monkeypatch it); this layer only shapes requests, renders, and redirects.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from intake_workflow.domain import api, eligibility, filings, layer2, packets
from intake_workflow.email.outbox import EmailSendError, get_provider
from intake_workflow.schemas import CaseStage, Milestone, OutreachStatus, PartyRole
from intake_workflow.store import Store
from intake_workflow.web.auth import require_staff
from intake_workflow.web.templating import templates

router = APIRouter(prefix="/staff", dependencies=[Depends(require_staff)])

REVIEWER = "Isaiah"
ATTORNEY = "Allison"

# Form types offered in the add-filing picker. Broader than the set of forms the
# packet builder can assemble (those live in packets.FORM_TYPES).
FILING_FORM_TYPES = ("I-130", "I-485", "I-765", "I-131", "I-751")


def _store(request: Request) -> Store:
    return request.app.state.store


def _parse_optional_date(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _staleness_key(case) -> datetime:
    """Most recent touch across parties; older = staler. Falls back to
    creation time when no party has any recorded activity."""
    touches = [p.last_activity_at for p in case.parties if p.last_activity_at]
    return max(touches) if touches else case.created_at


def _attorney_count(store: Store) -> int:
    """How many items are awaiting attorney review, across all cases. Degrades
    to 0 if the eligibility body isn't wired up yet (parallel-build safety) so
    the dashboard never 500s while the domain layer catches up."""
    try:
        return len(eligibility.attorney_queue(store))
    except NotImplementedError:
        return 0


def _filing_error(case_id: str, message: str) -> RedirectResponse:
    """Bounce back to the case detail with a readable flash — never a 500."""
    qs = urlencode({"filing_error": message})
    return RedirectResponse(f"/staff/case/{case_id}?{qs}", status_code=303)


@router.get("")
def dashboard(request: Request, drafted: int | None = None):
    store = _store(request)
    rows = []
    for case in store.list_cases():
        progress = api.case_progress(case)
        drafted_count = sum(1 for o in case.outreach if o.status == OutreachStatus.drafted)
        rows.append({
            "case": case,
            "progress": progress,
            "drafted": drafted_count,
            "stale": _staleness_key(case),
        })
    # Stalest (least recently touched) first; completed cases sink to the bottom.
    rows.sort(key=lambda r: (r["progress"].stage == CaseStage.complete, r["stale"]))
    radar = api.i751_radar(store)
    return templates.TemplateResponse(
        request,
        "staff/dashboard.html",
        {
            "rows": rows,
            "radar": radar,
            "flash_drafted": drafted,
            "attorney_count": _attorney_count(store),
        },
    )


@router.post("/tick")
def scheduler_tick(request: Request):
    store = _store(request)
    provider = get_provider()
    kwargs = {"provider": provider} if provider is not None else {}
    drafts = api.run_scheduler(store, **kwargs)
    return RedirectResponse(f"/staff?drafted={len(drafts)}", status_code=303)


@router.get("/case/new")
def new_case_form(request: Request):
    return templates.TemplateResponse(request, "staff/case_new.html")


@router.post("/case/new")
def create_case(
    request: Request,
    title: str = Form(...),
    petitioner_name: str = Form(...),
    petitioner_email: str = Form(...),
    beneficiary_name: str = Form(...),
    beneficiary_email: str = Form(...),
    consult_notes: str = Form(""),
    i485_approved_on: str = Form(""),
):
    store = _store(request)
    case = api.create_case(
        store,
        title=title,
        petitioner_name=petitioner_name,
        petitioner_email=petitioner_email,
        beneficiary_name=beneficiary_name,
        beneficiary_email=beneficiary_email,
        consult_notes=consult_notes,
        i485_approved_on=_parse_optional_date(i485_approved_on),
    )
    return RedirectResponse(f"/staff/case/{case.id}", status_code=303)


@router.get("/case/{case_id}")
def case_detail(request: Request, case_id: str):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    progress = api.case_progress(case)
    groups = {
        role: [i for i in case.items if i.assignee == role]
        for role in (PartyRole.petitioner, PartyRole.beneficiary)
    }
    drafted = [o for o in case.outreach if o.status == OutreachStatus.drafted]
    i751 = api.i751_dates(case.i485_approved_on) if case.i485_approved_on else None
    timeline = store.list_timeline(case_id)
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        request,
        "staff/case_detail.html",
        {
            "case": case,
            "progress": progress,
            "groups": groups,
            "drafted": drafted,
            "i751": i751,
            "timeline": timeline,
            "base_url": base_url,
            "packet_form_types": packets.FORM_TYPES,
            "filing_form_types": FILING_FORM_TYPES,
            "milestones": list(Milestone),
        },
    )


@router.post("/case/{case_id}/item/{item_key}/review")
def review_item(
    request: Request,
    case_id: str,
    item_key: str,
    action: str = Form(...),
    reason: str = Form(""),
):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        api.review_item(
            store, case, item_key,
            action=action, reviewer=REVIEWER, reason=(reason.strip() or None),
        )
    except ValueError:
        # e.g. a return with no reason — bounce back without a 500.
        return RedirectResponse(f"/staff/case/{case_id}?review_error=1", status_code=303)
    return RedirectResponse(f"/staff/case/{case_id}", status_code=303)


@router.post("/case/{case_id}/outreach/{outreach_id}/approve")
def approve_outreach(request: Request, case_id: str, outreach_id: str):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    provider = get_provider()
    kwargs = {"provider": provider} if provider is not None else {}
    try:
        api.approve_outreach(store, case, outreach_id, REVIEWER, **kwargs)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail="Outreach not found")
    except EmailSendError:
        return RedirectResponse(f"/staff/case/{case_id}?send_error=1", status_code=303)
    return RedirectResponse(f"/staff/case/{case_id}", status_code=303)


@router.post("/case/{case_id}/outreach/{outreach_id}/dismiss")
def dismiss_outreach(request: Request, case_id: str, outreach_id: str):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        api.dismiss_outreach(store, case, outreach_id, REVIEWER)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail="Outreach not found")
    return RedirectResponse(f"/staff/case/{case_id}", status_code=303)


@router.post("/case/{case_id}/layer2")
def run_layer2(request: Request, case_id: str):
    """Layer-2 LLM cross-document checks (flag-only; needs ANTHROPIC_API_KEY)."""
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    extractor = layer2.get_extractor()
    if extractor is None:
        return RedirectResponse(f"/staff/case/{case_id}?layer2=nokey", status_code=303)
    checked = layer2.run_layer2(store, case, extractor)
    return RedirectResponse(f"/staff/case/{case_id}?layer2={len(checked)}", status_code=303)


# ------------------------------------------------------------ filings (post-filing)

@router.post("/case/{case_id}/filings")
def add_filing(
    request: Request,
    case_id: str,
    form_type: str = Form(...),
    filed_on: str = Form(...),
    receipt_number: str = Form(""),
):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    filed = _parse_optional_date(filed_on)
    if filed is None:
        return _filing_error(case_id, "Please enter a valid filing date.")
    try:
        filings.record_filing(
            store, case,
            form_type=form_type.strip(),
            filed_on=filed,
            receipt_number=(receipt_number.strip() or None),
        )
    except ValueError as exc:
        return _filing_error(case_id, str(exc))
    return RedirectResponse(f"/staff/case/{case_id}", status_code=303)


@router.post("/case/{case_id}/filings/{filing_id}/receipt")
def set_filing_receipt(
    request: Request,
    case_id: str,
    filing_id: str,
    receipt_number: str = Form(...),
):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        filings.set_receipt_number(store, case, filing_id, receipt_number.strip())
    except ValueError as exc:
        return _filing_error(case_id, str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="Filing not found")
    return RedirectResponse(f"/staff/case/{case_id}", status_code=303)


@router.post("/case/{case_id}/filings/{filing_id}/status")
def set_filing_status(
    request: Request,
    case_id: str,
    filing_id: str,
    milestone: str = Form(...),
    note: str = Form(""),
    notify: str | None = Form(None),
):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        ms = Milestone(milestone)
    except ValueError:
        return _filing_error(case_id, "Please choose a valid milestone.")
    try:
        filings.update_filing_status(store, case, filing_id, milestone=ms, note=note.strip())
        # The checkbox is checked by default; when set, draft a client-facing
        # notification that flows into the normal follow-up approval queue.
        if notify is not None:
            filings.draft_status_update(store, case, filing_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Filing not found")
    return RedirectResponse(f"/staff/case/{case_id}", status_code=303)


@router.get("/case/{case_id}/packet/{form_type}")
def filing_packet(request: Request, case_id: str, form_type: str):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        packet = packets.build_packet(case, form_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")
    return templates.TemplateResponse(
        request, "staff/packet.html", {"case": case, "packet": packet},
    )


# ---------------------------------------------------------- attorney red-flag queue

@router.get("/attorney-queue")
def attorney_queue_page(request: Request):
    store = _store(request)
    entries = eligibility.attorney_queue(store)
    return templates.TemplateResponse(
        request, "staff/attorney_queue.html", {"entries": entries},
    )


@router.post("/case/{case_id}/item/{item_key}/clear-review")
def clear_review(
    request: Request,
    case_id: str,
    item_key: str,
    reviewer: str = Form(ATTORNEY),
    note: str = Form(""),
):
    store = _store(request)
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        eligibility.clear_attorney_review(
            store, case, item_key,
            reviewer=(reviewer.strip() or ATTORNEY), note=note.strip(),
        )
    except (KeyError, ValueError):
        # Unknown item or already-cleared: bounce back rather than 500.
        return RedirectResponse("/staff/attorney-queue?clear_error=1", status_code=303)
    return RedirectResponse("/staff/attorney-queue", status_code=303)
