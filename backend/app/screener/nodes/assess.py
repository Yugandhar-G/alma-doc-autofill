"""Per-criterion assessment node (Send fan-out target)."""
import logging

from app.config import get_settings
from app.schemas import CriterionAssessment
from app.screener.criteria import CRITERIA_BY_ID
from app.screener.intake import answer_index, render_intake
from app.screener.nodes import common
from app.screener.nodes.common import emit, render_matrix, render_verification
from app.screener.prompts import assess_prompt
from app.screener.state import AssessOneInput

logger = logging.getLogger("yunaki.screener.assess")


def _scan_payload(payload: AssessOneInput) -> dict:
    """What this node is genuinely about to read, straight from state:
    the intake answers and any reviewed evidence claims mapped to this
    criterion. Session-owner channel only."""
    state = payload.state
    claims = []
    if state.matrix is not None:
        claims = [
            {
                "claim": item.claim,
                "sources": [f"{ref.kind}:{ref.ref[:24]}" for ref in item.sources],
            }
            for item in state.matrix.items
            if payload.criterion_id in item.criterion_ids
        ]
    answers = answer_index(state.intake) if state.intake else {}
    return {
        "type": "evidence_scan",
        "node": "assess_one",
        "criterion_id": payload.criterion_id,
        "intake_answer_ids": sorted(answers.keys()),
        "matrix_claims": claims,
    }


async def assess_one(payload: AssessOneInput) -> dict:
    """One criterion, one structured call. Returns via the assessments
    reducer; per-criterion failure surfaces as a not_met + warning rather
    than aborting the whole run (slot-isolation, like /api/extract)."""
    settings = get_settings()
    spec = CRITERIA_BY_ID[payload.criterion_id]
    state = payload.state

    emit(_scan_payload(payload))

    intake_rendered = render_intake(state.intake) if state.intake else "(none)"
    matrix_rendered = (
        render_matrix(state.matrix) if state.matrix and state.matrix.items else None
    )
    verification_rendered = render_verification(state.verification)
    prompt = assess_prompt(spec, intake_rendered, matrix_rendered, verification_rendered)

    try:
        result = await common.generate(
            settings,
            prompt,
            CriterionAssessment,
            source_ref=spec.id,
            trace_name="gemini.screener.assess",
            live=state.live_feed,
            event_base={"node": "assess_one", "criterion_id": spec.id},
        )
    except Exception:
        logger.exception("assessment failed criterion=%s", spec.id)
        fallback = CriterionAssessment(
            criterion_id=spec.id,
            verdict="not_met",
            reasoning="Assessment could not be completed for this criterion; "
            "treated as unsupported rather than guessed.",
        )
        return {
            "assessments": [fallback],
            "warnings": [
                {
                    "field": f"assessments.{spec.id}",
                    "message": "The model call for this criterion failed; verdict "
                    "defaulted to not_met. Re-run to retry.",
                }
            ],
        }

    if result.criterion_id != spec.id:  # the model must not relabel its lane
        result = result.model_copy(update={"criterion_id": spec.id})

    emit(
        {
            "type": "finding",
            "node": "assess_one",
            "criterion_id": spec.id,
            "verdict": result.verdict,
            "reasoning": result.reasoning,
            "citations": [f"{ref.kind}:{ref.ref[:64]}" for ref in result.citations],
        }
    )
    return {"assessments": [result]}
