"""exhibit_index node — pure code, no LLM, no interrupt.

Sits between profile_summary and assemble_report. It derives the draft exhibit
index from the audited matrix (see app.screener.exhibits for the post-audit
equivalence argument) and writes it to state; assemble_report carries it into
the report. Attorney editing of the index arrives with the later shell phases —
this node only produces the draft."""
import logging

from app.screener.criteria import criteria_for_targets
from app.screener.exhibits import build_exhibit_index
from app.screener.intake import answer_index
from app.screener.nodes.common import emit
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.exhibits")


async def exhibit_index(state: ScreenerState) -> dict:
    applicable = [spec.id for spec in criteria_for_targets(list(state.visa_targets))]
    valid_answer_ids = frozenset(
        answer_index(state.intake).keys() if state.intake else ()
    )
    grounded_urls = frozenset(state.grounded_urls)

    index = build_exhibit_index(
        state.matrix,
        applicable,
        valid_answer_ids,
        state.evidence_docs,
        grounded_urls,
    )
    emit(
        {
            "type": "finding",
            "node": "exhibit_index",
            "exhibits": len(index.entries),
            "gaps": len(index.gaps),
        }
    )
    logger.info(
        "exhibit index built session=%s exhibits=%d gaps=%d",
        state.session_id, len(index.entries), len(index.gaps),
    )
    return {"exhibit_index": index}
