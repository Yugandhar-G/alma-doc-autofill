"""verify_profile node — runs the tool-loop verification agent over the
human-approved matrix. Reached only via the deterministic route in graph.py
(flag on AND key present AND claims exist)."""
import logging

from app.config import get_settings
from app.schemas import FieldWarning, ProfileVerification
from app.screener.agent import run_verification_agent
from app.screener.nodes.common import emit
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.verify")


async def verify_profile(state: ScreenerState) -> dict:
    settings = get_settings()
    if state.matrix is None or not state.matrix.items:
        return {}

    emit(
        {
            "type": "evidence_scan",
            "node": "verify_profile",
            "claims": [item.claim for item in state.matrix.items],
            "budget": settings.screener_agent_max_tool_calls,
        }
    )
    try:
        verification, transcript = await run_verification_agent(
            state.intake, state.matrix, settings, emit, live=state.live_feed
        )
    except Exception:
        logger.exception("verification agent failed session=%s", state.session_id)
        return {
            "verification": ProfileVerification(identity_confidence="low"),
            "warnings": [
                FieldWarning(
                    field="verification",
                    message="Online verification failed and was skipped; the "
                    "assessment relies on the provided record only.",
                )
            ],
        }

    emit(
        {
            "type": "finding",
            "node": "verify_profile",
            "identity_confidence": verification.identity_confidence,
            "verifications": [
                {"claim": v.claim, "status": v.status, "urls": v.evidence_urls}
                for v in verification.verifications
            ],
            "searched_but_absent": verification.searched_but_absent,
            "tool_calls_used": verification.tool_calls_used,
        }
    )
    warnings = [
        FieldWarning(
            field="verification",
            message=f'Claim "{v.claim[:80]}" is contradicted by public sources — '
            "assessors will treat it as unsupported.",
        )
        for v in verification.verifications
        if v.status == "contradicted"
    ]
    logger.info(
        "verification done session=%s tool_calls=%d verified=%d contradicted=%d",
        state.session_id,
        verification.tool_calls_used,
        sum(1 for v in verification.verifications if v.status == "verified"),
        len(warnings),
    )
    return {
        "verification": verification,
        "grounded_urls": transcript.seen_urls,
        "warnings": warnings,
    }
