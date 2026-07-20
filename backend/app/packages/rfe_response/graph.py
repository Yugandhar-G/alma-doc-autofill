"""RFE-response graph: extract_notice → parse_grounds → deadline_check →
response_checklist → review_gate (interrupt) → finalize → END.

Deterministic skeleton (fixed edges, no LLM picks the path). Exactly two model
calls exist in the whole run, both isolated to a single node each: the vision
extraction (extract_notice) and one checklist distillation (response_checklist).
parse_grounds, deadline_check, the checklist audit, and the cover assembly are
pure code. The review pause checkpoints, so an in-review run survives a reload.

Module-level seams patched offline in tests / eval, mirroring chase.py:
- ``extract_notice_document`` — the vision extraction,
- ``make_client`` / ``call_gemini`` — the direct checklist-distillation path,
- ``get_matter_store`` — the firm-scoped store for matter docs + memory.
"""
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.config import get_settings
from app.kernel.llm import call_gemini, make_client  # module-level: test seams
from app.kernel.memory.service import MemoryService
from app.kernel.store.base import TenantScope, get_matter_store  # module-level: seam
from app.packages.rfe_response.deadlines import deadline_status, is_critical
from app.packages.rfe_response.extraction import extract_notice_document  # seam
from app.packages.rfe_response.prompts import checklist_prompt
from app.packages.rfe_response.refs_audit import audit_checklist, build_cover_structure
from app.packages.rfe_response.schemas import (
    ChecklistItem,
    ResponseChecklist,
    RfeNotice,
    RfeResponseReport,
    RfeResponseState,
)

logger = logging.getLogger("yunaki.rfe_response.graph")


# --- helpers ---------------------------------------------------------------
def _has_matter(state: RfeResponseState) -> bool:
    return bool(state.matter_id and state.firm_id and state.user_id)


def _scope(state: RfeResponseState) -> TenantScope:
    return TenantScope(firm_id=state.firm_id or "", user_id=state.user_id or "")


def _report_ok(notice: RfeNotice, days: int | None, checklist: ResponseChecklist) -> bool:
    """ok = deadline verifiable and safe (>= 14 days) AND every ground covered by
    at least one audited checklist item."""
    if is_critical(days):
        return False
    addressed = {item.ground_id for item in checklist.items}
    return all(ground.ground_id in addressed for ground in notice.grounds)


def _assemble_report(state: RfeResponseState) -> RfeResponseReport:
    notice = state.notice or RfeNotice()
    checklist = state.checklist or ResponseChecklist()
    return RfeResponseReport(
        notice=notice,
        deadline_days_remaining=state.deadline_days_remaining,
        deadline_warning=state.deadline_warning,
        checklist=checklist,
        ok=_report_ok(notice, state.deadline_days_remaining, checklist),
    )


def _grounds_digest(notice: RfeNotice) -> str:
    """One-line grounds digest for the firm-memory summary."""
    form = notice.form_id or "unknown form"
    receipt = f", {notice.receipt_number}" if notice.receipt_number else ""
    return f"RFE ({form}{receipt}): {len(notice.grounds)} ground(s)"


async def _matter_doc_context(state: RfeResponseState) -> tuple[list[str], str]:
    """(doc_ids, prompt lines) for the matter's documents, or empty + a
    notice-only note when there is no matter context. Degrades gracefully."""
    if not _has_matter(state):
        return [], "(no matter attached — respond from the notice alone)"
    store = get_matter_store()
    docs = await store.list_documents(_scope(state), state.matter_id)  # type: ignore[arg-type]
    ids = [doc.doc_id for doc in docs]
    lines = "\n".join(f"[{doc.doc_id}] {doc.doc_type}" for doc in docs) or "(none on file)"
    return ids, lines


# --- nodes -----------------------------------------------------------------
async def extract_notice(state: RfeResponseState) -> dict:
    """Vision extraction → RfeNotice (grounds included in the same call). Clears
    the raw bytes so they never reach the review checkpoint. A notice injected
    directly into state (tests / eval) is left untouched; empty input yields an
    honest empty notice rather than a guess."""
    if state.notice is not None:
        return {}
    if not state.notice_bytes:
        return {"notice": RfeNotice()}
    notice = await extract_notice_document(state.notice_bytes, state.notice_filename)
    logger.info("rfe extract_notice run=%s grounds=%d", state.run_id, len(notice.grounds))
    return {"notice": notice, "notice_bytes": None}


async def parse_grounds(state: RfeResponseState) -> dict:
    """PURE CODE: normalize the grounds that extract_notice already returned — no
    second LLM call. Drops grounds with empty verbatim text (nothing to cite) and
    reassigns contiguous, stable ground ids (g1, g2, ...) so the downstream refs
    audit has a deterministic ground-id set to check against."""
    notice = state.notice or RfeNotice()
    cleaned: list = []
    for ground in notice.grounds:
        if not ground.quoted_text.strip():
            continue
        cleaned.append(ground.model_copy(update={"ground_id": f"g{len(cleaned) + 1}"}))
    logger.info(
        "rfe parse_grounds run=%s kept=%d dropped=%d",
        state.run_id, len(cleaned), len(notice.grounds) - len(cleaned),
    )
    return {"notice": notice.model_copy(update={"grounds": cleaned})}


async def deadline_check(state: RfeResponseState) -> dict:
    """PURE CODE date math against state.today (never datetime.now()). Null /
    unparseable deadline → None + an explicit confirm-manually warning."""
    deadline = state.notice.response_deadline if state.notice else None
    days, warning = deadline_status(deadline, state.today)
    logger.info("rfe deadline_check run=%s days=%s", state.run_id, days)
    return {"deadline_days_remaining": days, "deadline_warning": warning}


async def response_checklist(state: RfeResponseState) -> dict:
    """ONE distillation call mapping each ground to actions + doc kinds, then a
    PURE-CODE audit (strip fabricated grounds / invented refs) and a code-
    assembled cover structure. Skips the LLM entirely when there are no grounds
    (an empty checklist needs no model)."""
    notice = state.notice or RfeNotice()
    if not notice.grounds:
        return {"checklist": ResponseChecklist(), "warnings": []}

    ground_ids = [ground.ground_id for ground in notice.grounds]
    matter_doc_ids, matter_doc_lines = await _matter_doc_context(state)
    settings = get_settings()
    raw: ResponseChecklist = await call_gemini(  # type: ignore[assignment]
        make_client(settings),
        settings.gemini_model,
        checklist_prompt(notice, matter_doc_lines),
        ResponseChecklist,
        settings,
        trace_name="gemini.rfe_response.checklist",
    )
    kept, warnings = audit_checklist(raw.items, ground_ids, matter_doc_ids)
    cover = build_cover_structure(notice.grounds, kept)
    logger.info(
        "rfe response_checklist run=%s items=%d dropped=%d",
        state.run_id, len(kept), len(warnings),
    )
    return {
        "checklist": ResponseChecklist(items=kept, cover_structure=cover),
        "warnings": warnings,
    }


async def review_gate(state: RfeResponseState) -> dict:
    """Human gate carrying the draft report + audit warnings. Resume returns the
    approved checklist (edits re-validate through the same ResponseChecklist
    schema); the cover structure is re-derived in code from the approved items so
    it can never reference an unaddressed ground. A resume with no checklist keeps
    the audited draft unchanged."""
    draft = _assemble_report(state)
    resume = interrupt(
        {"report": draft.model_dump(), "warnings": list(state.warnings)}
    ) or {}
    checklist_in = resume.get("checklist")
    if checklist_in is None:
        approved = state.checklist or ResponseChecklist()
    else:
        approved = ResponseChecklist.model_validate(checklist_in)
    grounds = (state.notice or RfeNotice()).grounds
    cover = build_cover_structure(grounds, approved.items)
    return {"checklist": approved.model_copy(update={"cover_structure": cover})}


async def finalize(state: RfeResponseState) -> dict:
    """Terminal: re-stamp the report from the approved checklist and, when a
    matter is attached, record the RFE to firm memory (kind="rfe",
    criterion_key=form_id) — the loop-closer that lets future Pre-Flight runs
    recall this firm's RFE patterns. A notice-only run skips the write."""
    report = _assemble_report(state)
    notice = state.notice
    if _has_matter(state) and notice is not None:
        store = get_matter_store()
        await MemoryService(store).record(
            _scope(state),
            matter_id=state.matter_id,  # type: ignore[arg-type]
            run_id=state.run_id or None,
            matter_type=state.matter_type,
            kind="rfe",
            summary=_grounds_digest(notice),
            criterion_key=notice.form_id,
            detail={
                "grounds": [ground.model_dump() for ground in notice.grounds],
                "response_deadline": notice.response_deadline,
                "deadline_days_remaining": state.deadline_days_remaining,
            },
        )
        logger.info("rfe finalize recorded memory run=%s matter=%s", state.run_id, state.matter_id)
    return {"report": report}


def build_graph(checkpointer=None):
    """Compile the RFE-response graph. Checkpointer injected — tests use a temp
    saver, the API owns the real one (review must survive reloads)."""
    graph = StateGraph(RfeResponseState)
    graph.add_node("extract_notice", extract_notice)
    graph.add_node("parse_grounds", parse_grounds)
    graph.add_node("deadline_check", deadline_check)
    graph.add_node("response_checklist", response_checklist)
    graph.add_node("review_gate", review_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "extract_notice")
    graph.add_edge("extract_notice", "parse_grounds")
    graph.add_edge("parse_grounds", "deadline_check")
    graph.add_edge("deadline_check", "response_checklist")
    graph.add_edge("response_checklist", "review_gate")
    graph.add_edge("review_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
