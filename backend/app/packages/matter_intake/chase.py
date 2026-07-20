"""Chase agent + graph: classify_arrivals → reason_gaps (agent) → chase_review
(interrupt) → finalize.

- classify_arrivals: PURE CODE. Surfaces detected-vs-filed document-type
  mismatches from each attached document's stored extraction — no LLM.
- reason_gaps: the deepagents firm-data loop reasoning over the case-type
  requirements registry, then a distilled + DETERMINISTICALLY AUDITED gap list,
  then a drafted (never sent) client message per surviving gap. The audit is the
  anti-fabrication core: a gap citing a ref the agent never saw is stripped; an
  uncited "missing" claim survives only when CODE confirms the store genuinely
  lacks that required document — a "missing" claim for a document that EXISTS is
  dropped with a warning (the worst defect class).
- chase_review: a human gate carrying the audited gaps + drafts. NO LLM here, so
  the interrupt/resume replay is cheap and deterministic (drafting already
  happened in reason_gaps).
- finalize: records the approved gaps to firm memory (kind=outcome_note).

Module-level seams (get_matter_store / get_store / loop.*) are patched offline
in tests exactly as the screener agent's seams are."""
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.config import get_settings
from app.kernel.memory.service import MemoryService
from app.kernel.store.base import TenantScope, get_matter_store  # module-level: seam
from app.packages.matter_intake import loop
from app.packages.matter_intake.prompts import (
    chase_distill_prompt,
    chase_draft_prompt,
    chase_task_prompt,
)
from app.packages.matter_intake.refs_audit import (
    is_code_verified_absence,
    normalize_kind,
    surviving_refs,
)
from app.packages.matter_intake.schemas import (
    ChaseDraft,
    ChaseState,
    ClassifiedArrival,
    GapFinding,
    GapFindings,
)
from app.packages.preflight.knowledge.requirements import requirements_for
from app.storage.base import get_store  # module-level: seam (doc/extraction store)

logger = logging.getLogger("yunaki.matter_intake.chase")

_GRANTS = ("list_matter_docs", "read_extraction", "recall_memory")
_MAX_TOOL_CALLS = 6


def _scope(state: ChaseState) -> TenantScope:
    return TenantScope(firm_id=state.firm_id, user_id=state.user_id)


async def _extraction_detected(doc_store, doc_id: str, doc_type: str) -> str:
    """The stored extraction's detected type (final over raw), or 'unknown'."""
    env = await doc_store.get_extraction(doc_id, doc_type, "final")
    if env is None:
        env = await doc_store.get_extraction(doc_id, doc_type, "raw")
    return env.document_type_detected if env is not None else "unknown"


async def classify_arrivals(state: ChaseState) -> dict:
    """PURE CODE: for each attached document, compare its stored extraction's
    detected type against the type it was filed under. A concrete mismatch
    (detected is a real type other than the filed one) is surfaced for review."""
    scope = _scope(state)
    store = get_matter_store()
    doc_store = get_store()
    arrivals: list[ClassifiedArrival] = []
    for doc in await store.list_documents(scope, state.matter_id):
        detected = await _extraction_detected(doc_store, doc.doc_id, doc.doc_type)
        mismatch = detected not in (doc.doc_type, "unknown")
        arrivals.append(
            ClassifiedArrival(
                doc_id=doc.doc_id, doc_type=doc.doc_type, detected=detected, mismatch=mismatch
            )
        )
    logger.info(
        "chase classify matter=%s docs=%d mismatches=%d",
        state.matter_id, len(arrivals), sum(a.mismatch for a in arrivals),
    )
    return {"arrivals": arrivals}


async def _audit_gaps(
    findings: GapFindings, seen_refs: list[str], present_types: set[str], required_types: set[str]
) -> tuple[list[GapFinding], list[str]]:
    """Deterministic: strip fabricated / uncited gaps.

    - refs present → keep only refs the agent saw; drop the finding (warn) if
      none survive.
    - refs empty → an absence claim: keep ONLY when code confirms a genuine gap
      (required kind, nothing attached). A claim about a doc that EXISTS is the
      fabrication class → drop + warn."""
    kept: list[GapFinding] = []
    warnings: list[str] = []
    for f in findings.findings:
        if f.refs:
            valid = surviving_refs(f.refs, seen_refs)
            if valid:
                kept.append(f.model_copy(update={"refs": valid}))
            else:
                warnings.append(f"dropped gap {f.doc_kind!r}: cited refs never seen this run")
            continue
        dk = normalize_kind(f.doc_kind)
        if dk in present_types:
            warnings.append(
                f"dropped fabricated missing-document claim {f.doc_kind!r}: that document is attached"
            )
        elif is_code_verified_absence(f.doc_kind, required_types, present_types):
            kept.append(f)
        else:
            warnings.append(f"dropped uncited gap {f.doc_kind!r}: not a code-verified absence")
    return kept, warnings


async def reason_gaps(state: ChaseState) -> dict:
    """The firm-data agent loop → distilled → audited gaps → drafted messages."""
    scope = _scope(state)
    store = get_matter_store()
    settings = get_settings()
    reqs = requirements_for(state.case_type)

    transcript = await loop.run_firm_agent(
        scope=scope, store=store, settings=settings,
        prompt=chase_task_prompt(state.matter_id, state.case_type, reqs, _MAX_TOOL_CALLS),
        grants=_GRANTS, max_tool_calls=_MAX_TOOL_CALLS, node="reason_gaps",
    )
    findings: GapFindings = await loop.distill(
        settings,
        chase_distill_prompt(state.case_type, transcript.log, transcript.seen_refs),
        GapFindings,
        trace_name="gemini.matter_intake.reason_gaps.distill",
    )

    # Code-verified ground truth for the absence audit (never the model's word).
    docs = await store.list_documents(scope, state.matter_id)
    present_types = {normalize_kind(d.doc_type) for d in docs}
    required_types = {normalize_kind(r.doc_type) for r in (reqs.required if reqs else ())}
    gaps, warnings = await _audit_gaps(findings, transcript.seen_refs, present_types, required_types)

    language = _client_language(await store.get_matter(scope, state.matter_id))
    drafts = [await _draft_for(settings, gap, language) for gap in gaps]
    logger.info(
        "chase reason_gaps matter=%s kept=%d dropped=%d",
        state.matter_id, len(gaps), len(warnings),
    )
    return {"gaps": gaps, "drafts": drafts, "warnings": warnings}


def _client_language(matter) -> str:
    """The client's preferred language for chase messages. Matter carries no
    language field in v1, so this defaults to English; the getattr keeps the
    seam ready for the day the matter model grows the field."""
    return getattr(matter, "client_language", None) or "en"


async def _draft_for(settings, gap: GapFinding, language: str) -> ChaseDraft:
    draft: ChaseDraft = await loop.distill(
        settings, chase_draft_prompt(gap, language), ChaseDraft,
        trace_name="gemini.matter_intake.chase_draft",
    )
    return draft.model_copy(update={"doc_kind": gap.doc_kind, "language": draft.language or language})


async def chase_review(state: ChaseState) -> dict:
    """Human gate. Carries the audited gaps + drafts + audit warnings. Resume
    returns the approved gaps (edits re-validate through GapFinding); a resume
    with no gaps list keeps the audited set unchanged."""
    resume = interrupt(
        {
            "gaps": [g.model_dump() for g in state.gaps],
            "drafts": [d.model_dump() for d in state.drafts],
            "warnings": list(state.warnings),
            "arrivals": [a.model_dump() for a in state.arrivals],
        }
    ) or {}
    approved_in = resume.get("gaps")
    if approved_in is None:
        approved = list(state.gaps)
    else:
        approved = [GapFinding.model_validate(g) for g in approved_in]
    return {"gaps": approved}


async def finalize(state: ChaseState) -> dict:
    """Record the approved gaps to firm memory (outcome_note) and emit the
    report. Nothing is sent — the drafts are for a human to send."""
    scope = _scope(state)
    store = get_matter_store()
    kinds = ", ".join(g.doc_kind for g in state.gaps) or "none"
    summary = f"Document chase ({state.case_type}): {len(state.gaps)} gap(s) approved — {kinds}"
    await MemoryService(store).record(
        scope,
        matter_id=state.matter_id,
        run_id=state.run_id or None,
        matter_type=state.case_type,
        kind="outcome_note",
        summary=summary,
        detail={"gaps": [g.model_dump() for g in state.gaps]},
    )
    report = {
        "case_type": state.case_type,
        "gaps": [g.model_dump() for g in state.gaps],
        "drafts": [d.model_dump() for d in state.drafts],
        "arrivals": [a.model_dump() for a in state.arrivals],
        "warnings": list(state.warnings),
    }
    logger.info("chase finalize matter=%s gaps=%d", state.matter_id, len(state.gaps))
    return {"report": report}


def build_graph(checkpointer=None):
    """Compile the chase graph. Checkpointer injected — the review gate must
    survive a reload, exactly like preflight/screener."""
    graph = StateGraph(ChaseState)
    graph.add_node("classify_arrivals", classify_arrivals)
    graph.add_node("reason_gaps", reason_gaps)
    graph.add_node("chase_review", chase_review)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "classify_arrivals")
    graph.add_edge("classify_arrivals", "reason_gaps")
    graph.add_edge("reason_gaps", "chase_review")
    graph.add_edge("chase_review", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
