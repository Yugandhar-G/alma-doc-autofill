"""Extraction engine: upload bytes → guardrails → Gemini structured call →
post-validation → ExtractionEnvelope.

PII rule: log only content hashes, page counts, and model ids — never names,
numbers, or any extracted value.
"""
import hashlib
import logging
from functools import lru_cache
from typing import Any, Literal

from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError, create_model

from app.config import Settings, get_settings
from app.extraction import prompts, render
from app.observability import llm_generation, record_usage
from app.extraction.quality import assert_page_quality
from app.extraction.validators import validate_g28, validate_passport
from app.schemas import DocType, ExtractionEnvelope, FieldWarning, G28Data, PassportData

logger = logging.getLogger("alma.extraction.engine")

_DATA_MODEL: dict[DocType, type[BaseModel]] = {"passport": PassportData, "g28": G28Data}


@lru_cache
def _wrapper_model(doc_type: DocType) -> type[BaseModel]:
    """Response schema sent to Gemini: the target data model plus the
    document-type self-report used for wrong-document detection."""
    return create_model(
        f"{doc_type.capitalize()}ExtractionResponse",
        document_type_detected=(Literal["passport", "g28", "other"], ...),
        data=(_DATA_MODEL[doc_type], ...),
    )


def _all_fields_null(value: Any) -> bool:
    """True when every leaf in a dumped model is None (empty extraction)."""
    if isinstance(value, dict):
        return all(_all_fields_null(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_fields_null(v) for v in value)
    return value is None


def _safe_error_summary(exc: Exception) -> str:
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


async def _call_gemini(
    client: genai.Client,
    model: str,
    prompt: str,
    png_pages: list[bytes],
    wrapper: type[BaseModel],
    settings: Settings,
    source_hash: str,
) -> BaseModel:
    """One structured extraction call with retry on unparseable output.

    All pages of the document go in a single request so the model sees the
    whole form at once.
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
        # Trace carries hash/pages/tokens only — never page images or output values.
        with llm_generation(
            "gemini.extract",
            model=model,
            metadata={
                "source_hash": source_hash,
                "pages": len(png_pages),
                "attempt": attempt,
                "temperature": settings.extraction_temperature,
            },
        ) as generation:
            response = await client.aio.models.generate_content(
                model=model, contents=[prompt, *parts], config=config
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
                "unparseable model output source_hash=%s model=%s attempt=%d/%d issues=%s",
                source_hash, model, attempt, attempts, issues,
            )
    raise RuntimeError(
        f"Gemini model {model!r} returned output that failed schema validation "
        f"{attempts} time(s) for document {source_hash}. See server logs."
    )


async def extract_document(
    file_bytes: bytes, filename: str, doc_type: DocType
) -> ExtractionEnvelope:
    """Extract one document. Raises ValueError for guardrail rejections
    (user-actionable) and RuntimeError for model/configuration failures."""
    settings = get_settings()
    source_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.info(
        "extraction start doc_type=%s source_hash=%s size_bytes=%d",
        doc_type, source_hash, len(file_bytes),
    )

    pages = render.prepare_pages(file_bytes, settings)
    for index, page in enumerate(pages, start=1):
        assert_page_quality(page, f"Page {index}", settings)
    png_pages = [render.to_png_bytes(page) for page in pages]

    client = genai.Client(api_key=settings.require_gemini_key())
    wrapper = _wrapper_model(doc_type)
    prompt = prompts.extraction_prompt(doc_type)

    model_used = settings.gemini_model
    result = await _call_gemini(
        client, model_used, prompt, png_pages, wrapper, settings, source_hash
    )

    detected: str = result.document_type_detected  # type: ignore[attr-defined]
    empty = _all_fields_null(result.data.model_dump())  # type: ignore[attr-defined]
    if empty or detected in ("other", "unknown"):
        # The image passed quality gates, so a null-everything or "other"
        # result warrants one shot with the stronger model.
        logger.info(
            "escalating source_hash=%s reason=%s model=%s",
            source_hash,
            "all_fields_null" if empty else f"detected_{detected}",
            settings.gemini_model_escalation,
        )
        model_used = settings.gemini_model_escalation
        result = await _call_gemini(
            client, model_used, prompt, png_pages, wrapper, settings, source_hash
        )
        detected = result.document_type_detected  # type: ignore[attr-defined]

    warnings: list[FieldWarning] = []
    data_dump: dict[str, Any] | None = None
    if detected == doc_type:
        if doc_type == "passport":
            validated, warnings = validate_passport(result.data)  # type: ignore[attr-defined]
        else:
            validated, warnings = validate_g28(result.data)  # type: ignore[attr-defined]
        data_dump = validated.model_dump()
    else:
        # Wrong document in the slot: surface the mismatch, never extract anyway.
        warnings.append(
            FieldWarning(
                field="document_type_detected",
                message=(
                    f"A {doc_type} was requested but the file looks like "
                    f"'{detected}'. Extraction withheld — upload the correct document."
                ),
            )
        )

    logger.info(
        "extraction done source_hash=%s detected=%s model=%s warnings=%d pages=%d",
        source_hash, detected, model_used, len(warnings), len(pages),
    )
    return ExtractionEnvelope(
        document_type_requested=doc_type,
        document_type_detected=detected,  # type: ignore[arg-type]
        data=data_dump,
        warnings=warnings,
        model_used=model_used,
        source_hash=source_hash,
    )
