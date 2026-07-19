"""Kernel LLM plumbing — the shared Gemini structured-call contract.

Every package's model access goes through here: one retry/validation/tracing
convention instead of per-package calling code. Lifted from app/llm.py (which
itself was lifted from extraction/engine.py); make_client moved up from
screener/nodes/common.py so tools and agents no longer import a node module.

PII rule (unchanged): log only content hashes, trace names, and error
*shapes* — never prompt text, page images, or model output values.
"""
import asyncio
import logging
from typing import Any, Sequence

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.kernel.observability import llm_generation, record_usage

logger = logging.getLogger("yunaki.llm")

_TRANSIENT_CODES = (429, 500, 503)
_TRANSIENT_BACKOFFS = (2.0, 5.0)  # seconds; len = extra attempts


def make_client(settings: Settings) -> genai.Client:
    """The one Gemini client factory. Raises with an actionable message when
    the key is absent (settings.require_gemini_key)."""
    return genai.Client(api_key=settings.require_gemini_key())


async def _generate_with_transient_retry(coro_factory, *, trace_name: str, source_ref: str):
    """Retry capacity/rate transient failures (429/500/503) with short backoff.
    Schema-validation retries are handled separately by the caller's loop."""
    for backoff in (*_TRANSIENT_BACKOFFS, None):
        try:
            return await coro_factory()
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            if backoff is None or code not in _TRANSIENT_CODES:
                raise
            logger.warning(
                "transient gemini error code=%s trace=%s ref=%s — retrying in %.0fs",
                code, trace_name, source_ref, backoff,
            )
            await asyncio.sleep(backoff)
    raise RuntimeError("unreachable")


def safe_error_summary(exc: Exception) -> str:
    """PII-safe diagnostics: field paths and error types only — never input
    values. str(ValidationError) embeds input_value=<raw model output>, which
    would leak extracted PII into logs and API error responses."""
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(loc) for loc in error['loc']) or '<root>'}:{error['type']}"
            for error in exc.errors(include_input=False, include_url=False)
        ]
        return "; ".join(parts) or exc.title
    return type(exc).__name__


async def call_gemini(
    client: genai.Client,
    model: str,
    prompt: str,
    wrapper: type[BaseModel],
    settings: Settings,
    *,
    png_pages: Sequence[bytes] = (),
    source_ref: str = "",
    trace_name: str = "gemini.call",
    metadata: dict[str, Any] | None = None,
) -> BaseModel:
    """One structured call with retry on unparseable output.

    ``png_pages`` (all pages in a single request, so the model sees the whole
    document at once) is optional — assessment-style calls are text-only.
    ``source_ref`` is a PII-safe identifier (content hash or criterion id)
    used in logs and traces.
    """
    parts = [
        genai_types.Part.from_bytes(data=page, mime_type="image/png") for page in png_pages
    ]
    config = genai_types.GenerateContentConfig(
        temperature=settings.extraction_temperature,
        response_mime_type="application/json",
        response_schema=wrapper,
    )
    attempts = settings.extraction_max_retries + 1
    for attempt in range(1, attempts + 1):
        # Trace carries ref/pages/tokens only — never page images or output values.
        with llm_generation(
            trace_name,
            model=model,
            metadata={
                "source_ref": source_ref,
                "pages": len(parts),
                "attempt": attempt,
                "temperature": settings.extraction_temperature,
                **(metadata or {}),
            },
        ) as generation:
            response = await _generate_with_transient_retry(
                lambda: client.aio.models.generate_content(
                    model=model, contents=[prompt, *parts], config=config
                ),
                trace_name=trace_name,
                source_ref=source_ref,
            )
            record_usage(generation, getattr(response, "usage_metadata", None))
        parsed = response.parsed
        if isinstance(parsed, wrapper):
            return parsed
        try:
            return wrapper.model_validate_json(response.text or "")
        except (ValidationError, ValueError) as exc:
            # PII rule: never log or raise str(exc) — ValidationError text
            # embeds input_value fragments of the model's raw output.
            issues = (
                [(e["loc"], e["type"]) for e in exc.errors(include_input=False)][:5]
                if isinstance(exc, ValidationError)
                else type(exc).__name__
            )
            logger.warning(
                "unparseable model output trace=%s ref=%s model=%s attempt=%d/%d issues=%s",
                trace_name, source_ref, model, attempt, attempts, issues,
            )
    raise RuntimeError(
        f"Gemini model {model!r} returned output that failed schema validation "
        f"{attempts} time(s) for {trace_name} ({source_ref}). See server logs."
    )


async def call_gemini_stream(
    client: genai.Client,
    model: str,
    prompt: str,
    wrapper: type[BaseModel],
    settings: Settings,
    *,
    on_thought,
    source_ref: str = "",
    trace_name: str = "gemini.call",
) -> BaseModel:
    """Structured call with the model's thought summaries streamed out as they
    arrive (thinking_config.include_thoughts) — this is the live "thinking out
    loud" feed, genuine model reasoning, never templated text.

    ``on_thought(str)`` receives each thought-summary chunk. The final answer
    text is accumulated and validated against the wrapper exactly like
    call_gemini. Single attempt: on any failure the caller falls back to
    call_gemini, which owns the retry ladder.
    """
    config = genai_types.GenerateContentConfig(
        temperature=settings.extraction_temperature,
        response_mime_type="application/json",
        response_schema=wrapper,
        thinking_config=genai_types.ThinkingConfig(include_thoughts=True),
    )
    answer_chunks: list[str] = []
    with llm_generation(
        trace_name,
        model=model,
        metadata={"source_ref": source_ref, "streamed": True},
    ) as generation:
        usage = None
        async for chunk in await client.aio.models.generate_content_stream(
            model=model, contents=[prompt], config=config
        ):
            usage = getattr(chunk, "usage_metadata", None) or usage
            for candidate in chunk.candidates or []:
                if candidate.content is None:
                    continue
                for part in candidate.content.parts or []:
                    if not part.text:
                        continue
                    if getattr(part, "thought", False):
                        on_thought(part.text)
                    else:
                        answer_chunks.append(part.text)
        record_usage(generation, usage)
    try:
        return wrapper.model_validate_json("".join(answer_chunks))
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "unparseable streamed output trace=%s ref=%s model=%s issues=%s",
            trace_name, source_ref, model, safe_error_summary(exc),
        )
        raise
