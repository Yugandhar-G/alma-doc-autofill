"""compile_matrix node: everything the user provided → EvidenceMatrix
(claim → criteria mapping with citations), pre-audited so the human reviews
a matrix whose every source is already verifiable."""
import logging

from app.config import get_settings
from app.schemas import EvidenceMatrix, FieldWarning
from app.screener.citations import audit_refs, _doc_corpus
from app.screener.criteria import CRITERIA_BY_ID, criteria_for_targets
from app.screener.intake import answer_index, render_intake
from app.screener.nodes import common
from app.screener.nodes.common import emit, short_hash
from app.screener.prompts import compile_prompt
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.compile")

_MAX_ITEMS = 100  # schema-side maxItems is rejected by Gemini; enforced here


def _render_docs(state: ScreenerState) -> str:
    blocks = []
    for doc in state.evidence_docs:
        facts = "\n".join(f'  - "{fact}"' for fact in doc.key_facts) or "  (no facts extracted)"
        blocks.append(
            f"DOCUMENT sha256={doc.source_hash} kind={doc.document_kind_detected}"
            + (f' title="{doc.title}"' if doc.title else "")
            + f"\n{facts}"
        )
    return "\n\n".join(blocks) if blocks else "(no documents uploaded)"


def _sanitize(matrix: EvidenceMatrix, state: ScreenerState) -> tuple[EvidenceMatrix, list[FieldWarning]]:
    """Deterministic cleanup before the human sees it: strip unverifiable
    sources, drop items left sourceless, drop unknown criterion ids, and
    recompute unmapped_docs from what actually got mapped."""
    valid_answers = frozenset(answer_index(state.intake).keys() if state.intake else ())
    corpus = _doc_corpus(state.evidence_docs)
    warnings: list[FieldWarning] = []
    items = []
    dropped = 0
    overflow = matrix.items[_MAX_ITEMS:]
    if overflow:
        warnings.append(
            FieldWarning(
                field="matrix.items",
                message=f"Matrix truncated to {_MAX_ITEMS} claims "
                f"({len(overflow)} dropped).",
            )
        )
    for item in matrix.items[:_MAX_ITEMS]:
        # grounded_urls + valid_memory_ids both empty here: matrix compilation
        # never consults web enrichment or firm memory (see screener contract).
        kept_refs, stripped = audit_refs(
            item.sources, valid_answers, corpus, frozenset(), frozenset()
        )
        known_criteria = [cid for cid in item.criterion_ids if cid in CRITERIA_BY_ID]
        if not kept_refs:
            dropped += 1
            continue
        items.append(
            item.model_copy(update={"sources": kept_refs, "criterion_ids": known_criteria})
        )
        if stripped:
            warnings.append(
                FieldWarning(
                    field="matrix.items",
                    message=f"{stripped} unverifiable source(s) removed from claim "
                    f'"{item.claim[:80]}".',
                )
            )
    if dropped:
        warnings.append(
            FieldWarning(
                field="matrix.items",
                message=f"{dropped} claim(s) had no verifiable source and were dropped "
                "before review.",
            )
        )
    mapped_hashes = {
        ref.ref for item in items for ref in item.sources if ref.kind == "doc"
    }
    unmapped = [
        doc.source_hash for doc in state.evidence_docs if doc.source_hash not in mapped_hashes
    ]
    return EvidenceMatrix(items=items, unmapped_docs=unmapped), warnings


async def compile_matrix(state: ScreenerState) -> dict:
    settings = get_settings()

    # Genuine scan feed: exactly what this node is about to read, per doc.
    for doc in state.evidence_docs:
        emit(
            {
                "type": "evidence_scan",
                "node": "compile_matrix",
                "doc": short_hash(doc.source_hash),
                "kind": doc.document_kind_detected,
                "title": doc.title,
                "facts": doc.key_facts,
            }
        )
    if state.intake is not None:
        emit(
            {
                "type": "evidence_scan",
                "node": "compile_matrix",
                "intake_answer_ids": sorted(answer_index(state.intake).keys()),
            }
        )

    criterion_ids = ", ".join(
        spec.id for spec in criteria_for_targets(list(state.visa_targets))
    )
    prompt = compile_prompt(
        render_intake(state.intake) if state.intake else "(none)",
        _render_docs(state),
        criterion_ids,
    )
    try:
        raw = await common.generate(
            settings,
            prompt,
            EvidenceMatrix,
            source_ref=state.session_id[:8],
            trace_name="gemini.screener.compile",
            live=state.live_feed,
            event_base={"node": "compile_matrix"},
        )
    except Exception:
        logger.exception("matrix compilation failed session=%s", state.session_id)
        empty = EvidenceMatrix(
            items=[], unmapped_docs=[d.source_hash for d in state.evidence_docs]
        )
        return {
            "matrix": empty,
            "warnings": [
                FieldWarning(
                    field="matrix",
                    message="Evidence-matrix compilation failed; review starts "
                    "from an empty matrix. Add claims manually or re-run.",
                )
            ],
        }

    matrix, warnings = _sanitize(raw, state)
    emit(
        {
            "type": "finding",
            "node": "compile_matrix",
            "claims": [
                {"claim": item.claim, "criteria": item.criterion_ids} for item in matrix.items
            ],
            "unmapped_docs": [short_hash(h) for h in matrix.unmapped_docs],
        }
    )
    return {"matrix": matrix, "warnings": warnings}
