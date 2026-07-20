"""review_gate node — the human-in-the-loop interrupt. The graph pauses here
with the compiled matrix; the run resumes only when the user has confirmed or
edited it. Edited values re-validate through the same schemas and the same
source audit (a user edit cannot smuggle in an unverifiable citation)."""
import logging

from langgraph.types import interrupt

from app.schemas import EvidenceMatrix, FieldWarning
from app.screener.citations import audit_refs, _doc_corpus
from app.screener.intake import answer_index
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.review")


async def review_gate(state: ScreenerState) -> dict:
    matrix = state.matrix or EvidenceMatrix()
    edited_dump = interrupt({"matrix": matrix.model_dump()})

    edited = EvidenceMatrix.model_validate(edited_dump)
    valid_answers = frozenset(answer_index(state.intake).keys() if state.intake else ())
    corpus = _doc_corpus(state.evidence_docs)
    warnings: list[FieldWarning] = []
    items = []
    for item in edited.items:
        # grounded_urls + valid_memory_ids both empty: a human edit re-validates
        # against the same intake + doc corpus, never web/memory allow-lists.
        kept, stripped = audit_refs(
            item.sources, valid_answers, corpus, frozenset(), frozenset()
        )
        if stripped:
            warnings.append(
                FieldWarning(
                    field="matrix.items",
                    message=f"{stripped} source(s) on the edited claim "
                    f'"{item.claim[:80]}" could not be verified and were removed.',
                )
            )
        if kept:
            items.append(item.model_copy(update={"sources": kept}))
    reviewed = EvidenceMatrix(items=items, unmapped_docs=edited.unmapped_docs)
    logger.info(
        "matrix review complete session=%s claims=%d", state.session_id, len(items)
    )
    return {"matrix": reviewed, "matrix_reviewed": True, "warnings": warnings}
