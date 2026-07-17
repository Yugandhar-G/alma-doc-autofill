"""Per-visa verdict node: one structured call per targeted visa type.
met/likely counts are recomputed in code afterwards — the model narrates,
the code counts."""
import logging

from app.config import get_settings
from app.schemas import VisaVerdict
from app.screener.criteria import EB1A_THRESHOLD, O1A_THRESHOLD, criteria_for
from app.screener.nodes import common
from app.screener.nodes.common import count_verdicts, emit, render_assessments
from app.screener.prompts import verdict_prompt
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.verdict")

_THRESHOLDS = {"O1A": O1A_THRESHOLD, "EB1A": EB1A_THRESHOLD}


async def verdict(state: ScreenerState) -> dict:
    settings = get_settings()
    one_time_award = state.intake.one_time_major_award if state.intake else None
    merits_rendered = (
        f"conclusion={state.final_merits.conclusion}\n{state.final_merits.reasoning}"
        if state.final_merits
        else None
    )

    verdicts: list[VisaVerdict] = []
    warnings: list[dict] = []
    for visa in state.visa_targets:
        applicable = tuple(spec.id for spec in criteria_for(visa))
        met, likely = count_verdicts(state.assessments, applicable)
        emit(
            {
                "type": "evidence_scan",
                "node": "verdict",
                "visa": visa,
                "criteria_met": met,
                "criteria_likely": likely,
                "threshold": _THRESHOLDS[visa],
            }
        )
        prompt = verdict_prompt(
            visa,
            _THRESHOLDS[visa],
            ", ".join(applicable),
            render_assessments(state.assessments, applicable),
            merits_rendered if visa == "EB1A" else None,
            one_time_award,
        )
        try:
            result = await common.generate(
                settings,
                prompt,
                VisaVerdict,
                source_ref=visa,
                trace_name="gemini.screener.verdict",
                live=state.live_feed,
                event_base={"node": "verdict", "visa": visa},
            )
        except Exception:
            logger.exception("verdict call failed visa=%s", visa)
            warnings.append(
                {
                    "field": f"verdicts.{visa}",
                    "message": f"The {visa} verdict call failed; no recommendation "
                    "was produced for this visa type.",
                }
            )
            continue
        # The model narrates; the code counts.
        result = result.model_copy(
            update={"visa": visa, "criteria_met": met, "criteria_likely": likely}
        )
        emit(
            {
                "type": "finding",
                "node": "verdict",
                "visa": visa,
                "recommendation": result.recommendation,
                "confidence": result.confidence,
                "summary": result.summary,
            }
        )
        verdicts.append(result)
    return {"verdicts": verdicts, "warnings": warnings}
