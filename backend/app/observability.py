"""Observability plane — tracing primitives now live in app.kernel.observability
(Phase 1 of the OS build); this module re-exports them and keeps the two
package-typed summarizers (envelope_stats, report_stats) that the kernel must
not know about (they import autofill schemas). New code imports primitives
from app.kernel.observability.
"""
from typing import Any

from app.kernel.observability import (  # noqa: F401
    TelemetryValue,
    count_leaves as _count_leaves,
    flush,
    get_langfuse,
    llm_generation,
    mask_leaves as _mask_leaves,
    mask_value,
    record_frontend_event,
    record_usage,
    request_trace,
    stage_span,
)
from app.schemas import ExtractionEnvelope, PopulationReport


def envelope_stats(envelope: ExtractionEnvelope | dict[str, Any]) -> dict[str, Any]:
    """PII-safe summary of one extraction result for trace output."""
    if isinstance(envelope, dict):
        envelope = ExtractionEnvelope.model_validate(envelope)
    read, null = _count_leaves(envelope.data or {})
    return {
        "requested": envelope.document_type_requested,
        "detected": envelope.document_type_detected,
        "fields_read": read,
        "fields_null": null,
        "fields": _mask_leaves(envelope.data or {}),
        "warnings": len(envelope.warnings),
        "model_used": envelope.model_used,
        "source_hash": envelope.source_hash,
    }


def report_stats(report: PopulationReport) -> dict[str, Any]:
    """PII-safe summary of a population run — counts only, never values."""
    return {
        "target_url": report.target_url,
        "filled": report.filled,
        "skipped_null": report.skipped_null,
        "mismatches": report.mismatches,
        "errors": report.errors,
        "ok": report.ok,
        "entries": len(report.entries),
    }
