"""Kernel observability — Langfuse tracing primitives behind a no-op switch.

Every helper degrades to a no-op when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
are unset, so the app keeps its "GEMINI_API_KEY is the only required secret"
property. Tracing failures must never fail a request.

PII policy (stricter than the rest of the app): traces carry content hashes,
timings, token counts, page counts, field STATISTICS, and MASKED field
previews (mask_value: first character / date shape only, as guardrail
evidence) — never document bytes, rendered pages, raw extracted values, or
population expected/actual values.

Package-typed summarizers (envelope_stats, report_stats) live with their
packages — this module knows no package schemas.
"""
import logging
import os
import re
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from app.config import get_settings

logger = logging.getLogger("yunaki.observability")

# Metadata values the telemetry endpoint accepts from the frontend.
TelemetryValue = str | int | float | bool | None


@lru_cache
def get_langfuse():
    """Singleton Langfuse client, or None when tracing is not configured."""
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    try:
        # Langfuse v3 rides on OpenTelemetry; the OTel resource picks the
        # service name up from the environment at TracerProvider creation,
        # so it must be in place before the client is constructed (else
        # traces report service.name="unknown_service").
        os.environ.setdefault("OTEL_SERVICE_NAME", "yunaki-doc-autofill")
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("langfuse tracing enabled host=%s", settings.langfuse_host)
        return client
    except Exception:
        logger.exception("langfuse init failed — tracing disabled for this run")
        return None


@contextmanager
def request_trace(
    name: str, session_id: str | None, metadata: dict[str, Any] | None = None
) -> Iterator[Any]:
    """Root span for one API request, grouped under the frontend session id.

    Yields the Langfuse span (or None when disabled) so the caller can attach
    PII-safe output stats via span.update(output=...).
    """
    client = get_langfuse()
    if client is None:
        yield None
        return
    from langfuse import propagate_attributes

    with propagate_attributes(session_id=session_id or None, trace_name=name):
        with client.start_as_current_observation(
            name=name, as_type="span", metadata=metadata
        ) as span:
            yield span


@contextmanager
def stage_span(name: str, metadata: dict[str, Any] | None = None) -> Iterator[Any]:
    """Child span for a pipeline stage (guardrails, render, validate, fill)."""
    client = get_langfuse()
    if client is None:
        yield None
        return
    with client.start_as_current_observation(
        name=name, as_type="span", metadata=metadata
    ) as span:
        yield span


@contextmanager
def llm_generation(
    name: str, model: str, metadata: dict[str, Any] | None = None
) -> Iterator[Any]:
    """Generation span around one Gemini call. The caller reports token usage
    via record_usage(); prompt text and page images are deliberately not sent."""
    client = get_langfuse()
    if client is None:
        yield None
        return
    with client.start_as_current_observation(
        name=name, as_type="generation", metadata=metadata
    ) as generation:
        generation.update(model=model)
        yield generation


def record_usage(generation: Any, usage_metadata: Any) -> None:
    """Attach google-genai usage counts to a generation span, best effort."""
    if generation is None or usage_metadata is None:
        return
    try:
        generation.update(
            usage_details={
                "input": getattr(usage_metadata, "prompt_token_count", 0) or 0,
                "output": getattr(usage_metadata, "candidates_token_count", 0) or 0,
                "total": getattr(usage_metadata, "total_token_count", 0) or 0,
            }
        )
    except Exception:
        logger.exception("failed to record token usage")


def record_frontend_event(
    name: str, session_id: str | None, metadata: dict[str, TelemetryValue]
) -> bool:
    """One UI event (step transition, extraction outcome, error) from the
    frontend, grouped under its session. Returns whether it was recorded."""
    client = get_langfuse()
    if client is None:
        return False
    from langfuse import propagate_attributes

    try:
        with propagate_attributes(session_id=session_id or None):
            client.create_event(name=name, metadata=metadata)
        return True
    except Exception:
        logger.exception("failed to record frontend event")
        return False


_DATE_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MASK_MAX_LEN = 12  # cap so mask length only weakly reflects value length


def mask_value(value: Any) -> str:
    """Mask one extracted value for trace display.

    The point is guardrail evidence, not data: a date renders as ****-**-**
    (proof the ISO normalization ran), any other value keeps its first
    character only. Booleans and single characters render as one glyph.
    """
    if isinstance(value, bool):
        return "•"
    text = str(value)
    if _DATE_SHAPE.fullmatch(text):
        return "****-**-**"
    if len(text) <= 1:
        return "*"
    return text[0] + "*" * min(len(text) - 1, _MASK_MAX_LEN - 1)


def mask_leaves(value: Any) -> Any:
    """Mirror a dumped payload with every leaf masked; null leaves are
    dropped (their count belongs in a fields_null stat)."""
    if isinstance(value, dict):
        masked = {
            key: mask_leaves(child) for key, child in value.items() if child is not None
        }
        return {key: child for key, child in masked.items() if child not in ({}, None)}
    return mask_value(value)


def count_leaves(value: Any) -> tuple[int, int]:
    """(non_null, null) leaf counts of a dumped payload."""
    if isinstance(value, dict):
        read = null = 0
        for child in value.values():
            r, n = count_leaves(child)
            read += r
            null += n
        return read, null
    return (0, 1) if value is None else (1, 0)


def flush() -> None:
    """Drain the export queue — call on app shutdown."""
    client = get_langfuse()
    if client is not None:
        try:
            client.flush()
        except Exception:
            logger.exception("langfuse flush failed")
