"""Kazarian step-two final-merits node (EB-1A path only; routing is a pure
function in graph.py — this node runs only when the gate opened)."""
import logging

from app.config import get_settings
from app.schemas import FinalMeritsAssessment
from app.screener.criteria import criteria_for
from app.screener.intake import render_intake
from app.screener.nodes import common
from app.screener.nodes.common import emit, render_assessments
from app.screener.prompts import merits_prompt
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.merits")


async def final_merits(state: ScreenerState) -> dict:
    settings = get_settings()
    eb1a_ids = tuple(spec.id for spec in criteria_for("EB1A"))
    assessments_rendered = render_assessments(state.assessments, eb1a_ids)

    emit(
        {
            "type": "evidence_scan",
            "node": "final_merits",
            "weighing": [
                {"criterion_id": a.criterion_id, "verdict": a.verdict}
                for a in state.assessments
                if a.criterion_id in eb1a_ids
            ],
        }
    )

    prompt = merits_prompt(
        assessments_rendered,
        render_intake(state.intake) if state.intake else "(none)",
    )
    try:
        result = await common.generate(
            settings,
            prompt,
            FinalMeritsAssessment,
            source_ref="final_merits",
            trace_name="gemini.screener.merits",
            live=state.live_feed,
            event_base={"node": "final_merits"},
        )
    except Exception:
        logger.exception("final merits assessment failed")
        return {
            "final_merits": FinalMeritsAssessment(
                conclusion="uncertain",
                reasoning="The final-merits model call failed; the totality "
                "determination is left undecided rather than guessed.",
            ),
            "warnings": [
                {
                    "field": "final_merits",
                    "message": "Final-merits call failed; conclusion defaulted "
                    "to uncertain. Re-run to retry.",
                }
            ],
        }

    emit(
        {
            "type": "finding",
            "node": "final_merits",
            "conclusion": result.conclusion,
            "reasoning": result.reasoning,
        }
    )
    return {"final_merits": result}
