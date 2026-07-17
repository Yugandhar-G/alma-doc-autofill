"""profile_summary node — the user-facing synthesis: where the candidate is
strong, what makes them eligible, and what will bounce back. Runs after the
verdicts so it can speak to the whole record, verification included."""
import logging

from app.config import get_settings
from app.schemas import ProfileSummary
from app.screener.intake import render_intake
from app.screener.nodes import common
from app.screener.nodes.common import emit, render_assessments
from app.screener.prompts import summary_prompt
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.summary")


def _render_verification(state: ScreenerState) -> str:
    verification = state.verification
    if verification is None:
        return "(online verification did not run)"
    lines = [f"identity_confidence: {verification.identity_confidence}"]
    for v in verification.verifications:
        urls = ", ".join(v.evidence_urls) or "no sources"
        lines.append(f"- [{v.status}] {v.claim} ({urls}) {v.notes}".strip())
    if verification.searched_but_absent:
        lines.append("Searched but absent: " + "; ".join(verification.searched_but_absent))
    return "\n".join(lines)


def _render_verdicts(state: ScreenerState) -> str:
    return "\n".join(
        f"{v.visa}: {v.recommendation} (confidence {v.confidence}, "
        f"{v.criteria_met} met / {v.criteria_likely} likely) — {v.summary}"
        for v in state.verdicts
    ) or "(no verdicts)"


async def profile_summary(state: ScreenerState) -> dict:
    settings = get_settings()
    prompt = summary_prompt(
        render_intake(state.intake) if state.intake else "(none)",
        render_assessments(state.assessments),
        _render_verification(state),
        _render_verdicts(state),
    )
    try:
        result = await common.generate(
            settings,
            prompt,
            ProfileSummary,
            source_ref="profile_summary",
            trace_name="gemini.screener.summary",
            live=state.live_feed,
            event_base={"node": "profile_summary"},
        )
    except Exception:
        logger.exception("profile summary failed session=%s", state.session_id)
        return {
            "warnings": [
                {
                    "field": "profile_summary",
                    "message": "The profile summary could not be generated; "
                    "the per-criterion assessments below stand on their own.",
                }
            ]
        }
    emit(
        {
            "type": "finding",
            "node": "profile_summary",
            "headline": result.headline,
            "strengths": result.strengths,
            "risks": result.risks,
        }
    )
    return {"profile_summary": result}
