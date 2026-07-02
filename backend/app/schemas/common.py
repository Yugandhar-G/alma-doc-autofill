"""Shared envelope types used across extraction, population, and the API."""
from typing import Any, Literal

from pydantic import BaseModel, Field

DocType = Literal["passport", "g28"]
DetectedType = Literal["passport", "g28", "other", "unknown"]


class FieldWarning(BaseModel):
    field: str = Field(description="Dotted path, e.g. 'attorney.state'")
    message: str


class ExtractionEnvelope(BaseModel):
    """What the extraction plane returns for one document."""
    document_type_requested: DocType
    document_type_detected: DetectedType = "unknown"
    data: dict[str, Any] | None = None  # validated PassportData / G28Data dump
    warnings: list[FieldWarning] = Field(default_factory=list)
    model_used: str | None = None
    source_hash: str | None = Field(None, description="SHA-256 of the uploaded bytes; PII-safe log reference")


class PopulationEntry(BaseModel):
    selector: str
    source: str = Field(description="Dotted schema path the value came from")
    action: Literal["fill", "select_label", "select_value", "check"]
    status: Literal["filled", "skipped_null", "mismatch", "error"]
    expected: str | None = None
    actual: str | None = None


class PopulationReport(BaseModel):
    target_url: str
    entries: list[PopulationEntry] = Field(default_factory=list)
    filled: int = 0
    skipped_null: int = 0
    mismatches: int = 0
    errors: int = 0
    ok: bool = False
    artifact_id: str | None = Field(
        None,
        description="Content hash of the captured filled-form artifact; "
        "download via GET /api/population-artifact/{artifact_id}",
    )
    artifact_kind: Literal["pdf", "png"] | None = None


class ApiResponse(BaseModel):
    """Consistent envelope for every endpoint."""
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
