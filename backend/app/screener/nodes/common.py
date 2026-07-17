"""Shared node plumbing: the activity-feed emitter and prompt-side renderers.

Activity feed contract (FR9): every emitted event is derived from real state
or real model output — never a templated string pretending to be reasoning.
Events go to the session owner's SSE stream only; Langfuse traces are built
separately by PII-safe summarizers and never carry this content.
"""
import logging
from typing import Any

from google import genai
from pydantic import BaseModel

from app.config import Settings
from app.llm import call_gemini, call_gemini_stream
from app.schemas import CriterionAssessment, EvidenceMatrix, ProfileVerification

logger = logging.getLogger("yunaki.screener")


def _stream_writer():
    """The graph's custom stream writer, or None outside a streaming run."""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:
        return None


def emit(event: dict[str, Any]) -> None:
    """Push one activity event to the graph's custom stream, if streaming.

    Outside a streaming run (sync invoke, tests) there is no writer — the
    event is dropped, never buffered, never logged (it carries user content)."""
    writer = _stream_writer()
    if writer is None:
        return
    try:
        writer(event)
    except Exception:
        logger.debug("activity emit dropped (no active stream)")


def make_client(settings: Settings) -> genai.Client:
    return genai.Client(api_key=settings.require_gemini_key())


async def generate(
    settings: Settings,
    prompt: str,
    wrapper: type[BaseModel],
    *,
    source_ref: str,
    trace_name: str,
    live: bool = False,
    event_base: dict[str, Any] | None = None,
) -> BaseModel:
    """One structured node call. On live (SSE) runs the model's thought
    summaries are forwarded as model_thinking events (genuine reasoning, FR9);
    any streaming failure falls back to the plain call, which owns the retry
    ladder — output contract is identical either way. `live` comes from
    state.live_feed because langgraph hands out a no-op stream writer even in
    plain ainvoke, so writer presence alone can't gate the streaming path."""
    from app.llm import safe_error_summary

    client = make_client(settings)
    if live and _stream_writer() is not None:
        def on_thought(text: str) -> None:
            emit({**(event_base or {}), "type": "model_thinking", "text": text})

        try:
            return await call_gemini_stream(
                client,
                settings.gemini_model,
                prompt,
                wrapper,
                settings,
                on_thought=on_thought,
                source_ref=source_ref,
                trace_name=trace_name,
            )
        except Exception as exc:
            logger.warning(
                "streamed call failed, falling back trace=%s ref=%s cause=%s",
                trace_name, source_ref, safe_error_summary(exc),
            )
    return await call_gemini(
        client,
        settings.gemini_model,
        prompt,
        wrapper,
        settings,
        source_ref=source_ref,
        trace_name=trace_name,
    )


def short_hash(source_hash: str) -> str:
    return source_hash[:8]


def render_matrix(matrix: EvidenceMatrix, criterion_id: str | None = None) -> str:
    """Reviewed evidence items as prompt text, optionally filtered to one
    criterion. Sources rendered with the exact refs the model must re-cite."""
    lines: list[str] = []
    for item in matrix.items:
        if criterion_id is not None and criterion_id not in item.criterion_ids:
            continue
        sources = "; ".join(
            f"{ref.kind}:{ref.ref}" + (f' "{ref.excerpt}"' if ref.excerpt else "")
            for ref in item.sources
        )
        lines.append(f"- {item.claim} (criteria: {', '.join(item.criterion_ids) or 'unmapped'}) [{sources}]")
    return "\n".join(lines)


def render_verification(verification: "ProfileVerification | None") -> str | None:
    """The agent's verification results as prompt text, or None when the
    verification step did not run."""
    if verification is None or not verification.verifications:
        return None
    lines = [f"identity_confidence: {verification.identity_confidence}"]
    for v in verification.verifications:
        urls = ", ".join(v.evidence_urls) or "no confirming url"
        lines.append(f"- [{v.status}] {v.claim} (sources: {urls}) {v.notes}".rstrip())
    if verification.searched_but_absent:
        lines.append(
            "Searched but absent from the public record: "
            + "; ".join(verification.searched_but_absent)
        )
    return "\n".join(lines)


def render_assessments(
    assessments: list[CriterionAssessment], criterion_ids: tuple[str, ...] | None = None
) -> str:
    blocks = []
    for a in assessments:
        if criterion_ids is not None and a.criterion_id not in criterion_ids:
            continue
        gaps = "; ".join(a.gaps) or "none listed"
        blocks.append(
            f"[{a.criterion_id}] verdict={a.verdict}\n"
            f"  reasoning: {a.reasoning}\n"
            f"  gaps: {gaps}"
        )
    return "\n".join(blocks) if blocks else "(no assessments)"


def count_verdicts(
    assessments: list[CriterionAssessment], criterion_ids: tuple[str, ...]
) -> tuple[int, int]:
    """(met, likely) over the given criteria — computed in code, never
    trusted from the model."""
    met = sum(1 for a in assessments if a.criterion_id in criterion_ids and a.verdict == "met")
    likely = sum(
        1 for a in assessments if a.criterion_id in criterion_ids and a.verdict == "likely"
    )
    return met, likely
