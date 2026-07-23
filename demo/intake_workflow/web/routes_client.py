"""Client portal (magic-link) routes.

Contract with app/main.py: this module path and the ``router`` name are frozen.
Portal lives at /c/{token}. Every GET and POST records activity via the domain —
that timestamp is what the stall detector reads.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from intake_workflow.domain import api
from intake_workflow.domain.filings import USCIS_STATUS_URL
from intake_workflow.schemas import ItemState, Milestone
from intake_workflow.store import Store
from intake_workflow.web.templating import templates

router = APIRouter(prefix="/c")

_ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}

# Client-facing linear milestone track. ``rfe`` is out of band — inserted after
# biometrics only when it has actually occurred. ``decision`` collapses the
# approved/denied outcomes into one final step. Ranks drive done/current/upcoming.
_MILESTONE_RANK = {
    Milestone.filed: 0,
    Milestone.receipt: 1,
    Milestone.biometrics: 2,
    Milestone.rfe: 3,
    Milestone.interview: 4,
    Milestone.approved: 5,
    Milestone.denied: 5,
}
_CLIENT_STEPS = [
    (Milestone.filed, "Filed"),
    (Milestone.receipt, "Receipt notice"),
    (Milestone.biometrics, "Biometrics"),
    (Milestone.interview, "Interview"),
    ("decision", "Decision"),
]


def _step_state(rank: int, status_rank: int) -> str:
    if rank < status_rank:
        return "done"
    return "current" if rank == status_rank else "upcoming"


def _filing_steps(filing) -> list[dict]:
    """Presentational milestone steps for one filing. Never surfaces staff
    notes — only the milestone, its state, and the date it happened."""
    status_rank = _MILESTONE_RANK.get(filing.status, 0)
    has_rfe = filing.status == Milestone.rfe or any(
        u.milestone == Milestone.rfe for u in filing.updates
    )

    def latest_at(*milestones):
        ats = [u.at for u in filing.updates if u.milestone in milestones]
        return max(ats) if ats else None

    steps: list[dict] = []
    for milestone, label in _CLIENT_STEPS:
        if milestone == "decision":
            rank = 5
            at = latest_at(Milestone.approved, Milestone.denied)
            if filing.status == Milestone.approved:
                label = "Decision — approved"
        else:
            rank = _MILESTONE_RANK[milestone]
            at = latest_at(milestone)
        steps.append({"label": label, "state": _step_state(rank, status_rank), "at": at})
        if milestone == Milestone.biometrics and has_rfe:
            steps.append({
                "label": "Request for evidence",
                "state": "current" if filing.status == Milestone.rfe else "done",
                "at": latest_at(Milestone.rfe),
                "rfe": True,
            })
    return steps


def _filing_views(filings) -> list[dict]:
    """Warm, client-safe views of each filing for the portal timeline."""
    views = []
    for f in filings:
        views.append({
            "form_type": f.form_type,
            "receipt_number": f.receipt_number,
            "steps": _filing_steps(f),
            "latest_at": max((u.at for u in f.updates), default=None),
        })
    return views


def _store(request: Request) -> Store:
    return request.app.state.store


def _resolve(request: Request, token: str):
    """Return (case, party) for a token, or None. 404 is rendered by callers."""
    return _store(request).get_case_by_token(token)


def _not_found(request: Request):
    return templates.TemplateResponse(
        request, "client/notfound.html", status_code=404
    )


def _group_items(items) -> dict[str, list]:
    """Client-facing buckets, in display order:
    needs_attention (returned) → todo (pending) → in_review (submitted/
    flagged/checked) → done (accepted)."""
    groups: dict[str, list] = {"needs_attention": [], "todo": [], "in_review": [], "done": []}
    for item in items:
        state = item.state
        if state == ItemState.returned:
            groups["needs_attention"].append(item)
        elif state == ItemState.pending:
            groups["todo"].append(item)
        elif state == ItemState.accepted:
            groups["done"].append(item)
        else:  # submitted / flagged / checked
            groups["in_review"].append(item)
    return groups


@router.get("/{token}")
def portal(request: Request, token: str):
    resolved = _resolve(request, token)
    if resolved is None:
        return _not_found(request)
    case, party = resolved
    case = api.record_activity(_store(request), case, party.role)
    progress = api.case_progress(case)
    my_items = [i for i in case.items if i.assignee == party.role]
    groups = _group_items(my_items)
    thin_categories = [c for c in progress.coverage if not c.met]
    return templates.TemplateResponse(
        request,
        "client/portal.html",
        {
            "token": token,
            "case": case,
            "party": party,
            "progress": progress,
            "groups": groups,
            "thin_categories": thin_categories,
            "filing_views": _filing_views(case.filings),
            "uscis_url": USCIS_STATUS_URL,
        },
    )


@router.post("/{token}/item/{item_key}/upload")
async def upload_document(
    request: Request, token: str, item_key: str, file: UploadFile = File(...)
):
    resolved = _resolve(request, token)
    if resolved is None:
        return _not_found(request)
    case, party = resolved
    case = api.record_activity(_store(request), case, party.role)

    uploads_dir = Path(request.app.state.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    original = file.filename or "upload"
    ext = Path(original).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        ext = ext[:10]  # keep something, but never trust the client's extension
    safe_name = f"{uuid4().hex}{ext}"
    dest = uploads_dir / safe_name
    dest.write_bytes(await file.read())

    try:
        api.submit_document(
            _store(request), case, item_key, party.role,
            filename=original, stored_path=str(dest),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown checklist item")
    return RedirectResponse(f"/c/{token}", status_code=303)


@router.post("/{token}/item/{item_key}/answers")
async def submit_answers(request: Request, token: str, item_key: str):
    resolved = _resolve(request, token)
    if resolved is None:
        return _not_found(request)
    case, party = resolved
    case = api.record_activity(_store(request), case, party.role)

    item = next((i for i in case.items if i.key == item_key), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown checklist item")

    form = await request.form()
    answers = {f.key: str(form.get(f.key, "")) for f in item.fields}
    try:
        api.submit_answers(_store(request), case, item_key, party.role, answers)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown checklist item")
    return RedirectResponse(f"/c/{token}", status_code=303)
