"""FastAPI app — integration layer. Owns HTTP concerns only;
extraction/population/storage logic lives in the respective planes.

PII rule: request/response bodies carry extracted values by design; logs
never do — documents are referenced by content hash only.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.extraction import check_coherence, extract_document
from app.merge import merge_passport_envelopes
from app.observability import (
    envelope_stats,
    flush as observability_flush,
    record_frontend_event,
    report_stats,
    request_trace,
    TelemetryValue,
)
from app.population import populate_form
from app.population.artifact import stored_artifact_path
from app.screener.api import router as screener_router
from app.schemas import (
    ApiResponse,
    DocType,
    ExtractionEnvelope,
    FieldWarning,
    G28Data,
    PassportData,
)
from app.storage.base import get_store

logger = logging.getLogger("yunaki")
settings = get_settings()

@asynccontextmanager
async def _lifespan(_: FastAPI):
    yield
    observability_flush()  # drain the trace export queue on shutdown


app = FastAPI(title="yunaki-doc-autofill", lifespan=_lifespan)
app.include_router(screener_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STORAGE_WARNING = FieldWarning(
    field="storage",
    message="The extraction could not be persisted to storage; results are "
    "shown but no audit record was saved.",
)


class PopulateRequest(BaseModel):
    passport: PassportData | None = None
    g28: G28Data | None = None
    headed: bool | None = None


@app.get("/api/health")
async def health() -> ApiResponse:
    return ApiResponse(
        success=True,
        data={
            "storage": "supabase" if settings.supabase_enabled else "local",
            "model": settings.gemini_model,
            "gemini_key_present": settings.gemini_api_key is not None,
        },
    )


async def _read_capped(upload: UploadFile) -> bytes | None:
    """Read an upload without buffering past the size cap.

    Returns None when the cap is exceeded (checked via Content-Length first,
    then enforced while chunk-reading in case the header lies).
    """
    max_bytes = settings.max_file_mb * 1024 * 1024
    if upload.size is not None and upload.size > max_bytes:
        return None
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _save_guarded(save_coro, doc_label: str) -> bool:
    """Persist without letting a storage outage fail a successful extraction."""
    try:
        await save_coro
        return True
    except Exception:
        logger.exception("storage persistence failed for %s", doc_label)
        return False


async def _extract_one(
    upload: UploadFile, doc_type: DocType
) -> tuple[ExtractionEnvelope | dict, str | None]:
    """Extract one uploaded file → (envelope | {"error": ...}, doc_id).

    Guardrail rejections come back as {"error": ...} so the frontend can pin
    them to the offending slot. Storage failures degrade to a warning on the
    envelope — a working extraction is never discarded over persistence.
    """
    content = await _read_capped(upload)
    if content is None:
        return {"error": f"File exceeds the {settings.max_file_mb} MB limit."}, None
    try:
        envelope = await extract_document(content, upload.filename or "", doc_type)
    except ValueError as exc:  # guardrail rejection — user-actionable, re-upload
        return {"error": str(exc)}, None
    store = get_store()
    doc_id: str | None = None
    persisted = await _save_guarded(
        _persist_raw(store, content, doc_type, upload.filename or "", envelope),
        f"{doc_type} raw",
    )
    if persisted:
        doc_id = envelope.source_hash
    else:
        envelope = envelope.model_copy(
            update={"warnings": [*envelope.warnings, _STORAGE_WARNING]}
        )
    return envelope, doc_id


async def _persist_raw(
    store, content: bytes, doc_type: DocType, filename: str, envelope: ExtractionEnvelope
) -> None:
    doc_id = await store.save_document(content, doc_type, filename)
    await store.save_extraction(doc_id, envelope, kind="raw")


async def _persist_final(envelope_dump: dict, doc_id: str | None, label: str) -> None:
    """Persist the record the reviewer actually sees (post-merge/coherence)."""
    if doc_id is None:
        return
    store = get_store()
    envelope = ExtractionEnvelope.model_validate(envelope_dump)
    await _save_guarded(
        store.save_extraction(doc_id, envelope, kind="final"), f"{label} final"
    )


@app.post("/api/extract")
async def extract(
    request: Request,
    passport_front: UploadFile | None = None,
    passport_back: UploadFile | None = None,
    g28: UploadFile | None = None,
) -> ApiResponse:
    """Extract whichever documents were uploaded.

    Passport front and back are extracted separately and merged server-side
    (front authoritative, back fills nulls). Slot-level problems come back
    under the slot's key so one bad file never discards another's result.
    """
    if passport_front is None and g28 is None:
        return ApiResponse(
            success=False, error="Upload at least a passport front or a G-28."
        )
    try:
      with request_trace(
          "extract",
          request.headers.get("x-session-id"),
          metadata={
              "slot_passport_front": passport_front is not None,
              "slot_passport_back": passport_back is not None,
              "slot_g28": g28 is not None,
          },
      ) as trace:
        data: dict = {}

        if passport_back is not None and passport_front is None:
            data["passport_back"] = {
                "error": "Not processed — upload the passport front (photo page) "
                "along with the back."
            }

        front_doc_id: str | None = None
        if passport_front is not None:
            front, front_doc_id = await _extract_one(passport_front, "passport")
            if isinstance(front, dict):  # front rejected → slot error, no merge
                data["passport"] = front
                if passport_back is not None:
                    data["passport_back"] = {
                        "error": "Not processed — the front side was rejected."
                    }
            else:
                back: ExtractionEnvelope | None = None
                if passport_back is not None:
                    back_result, _ = await _extract_one(passport_back, "passport")
                    if isinstance(back_result, dict):
                        data["passport_back"] = back_result
                    else:
                        back = back_result
                data["passport"] = merge_passport_envelopes(front, back).model_dump()

        g28_doc_id: str | None = None
        if g28 is not None:
            g28_result, g28_doc_id = await _extract_one(g28, "g28")
            data["g28"] = (
                g28_result if isinstance(g28_result, dict) else g28_result.model_dump()
            )

        _attach_coherence_warnings(data)

        # Audit trail of what the reviewer is shown (raw records saved above).
        if isinstance(data.get("passport"), dict) and "error" not in data["passport"]:
            await _persist_final(data["passport"], front_doc_id, "passport")
        if isinstance(data.get("g28"), dict) and "error" not in data["g28"]:
            await _persist_final(data["g28"], g28_doc_id, "g28")

        if trace is not None:
            output: dict = {}
            for key in ("passport", "passport_back", "g28"):
                slot = data.get(key)
                if isinstance(slot, dict):
                    # Rejection reasons are fixed guardrail templates (size,
                    # blur, page cap, wrong type) — they name limits, never
                    # document content, so they are safe in the trace.
                    output[key] = (
                        {"rejected": True, "reason": slot["error"]}
                        if "error" in slot
                        else envelope_stats(slot)
                    )
            trace.update(output=output)
        return ApiResponse(success=True, data=data)
    except RuntimeError as exc:  # model/config failures — message is hash-only
        logger.exception("extraction runtime failure")
        return ApiResponse(success=False, error=str(exc))
    except Exception:
        logger.exception("extraction failed")
        return ApiResponse(success=False, error="Extraction failed. Check server logs.")


def _attach_coherence_warnings(data: dict) -> None:
    """Cross-document name check → warnings on the g28 envelope."""
    passport_env = data.get("passport")
    g28_env = data.get("g28")
    if not isinstance(passport_env, dict) or not isinstance(g28_env, dict):
        return
    if passport_env.get("data") is None or g28_env.get("data") is None:
        return
    passport = PassportData.model_validate(passport_env["data"])
    g28_data = G28Data.model_validate(g28_env["data"])
    for warning in check_coherence(passport, g28_data):
        g28_env.setdefault("warnings", []).append(warning.model_dump())


@app.post("/api/populate")
async def populate(request: Request, req: PopulateRequest) -> ApiResponse:
    if req.passport is None and req.g28 is None:
        return ApiResponse(success=False, error="Nothing to populate.")
    try:
        with request_trace(
            "populate",
            request.headers.get("x-session-id"),
            metadata={
                "has_passport": req.passport is not None,
                "has_g28": req.g28 is not None,
            },
        ) as trace:
            report = await populate_form(req.passport, req.g28, headed=req.headed)
            if trace is not None:
                trace.update(output=report_stats(report))
            return ApiResponse(success=True, data=report.model_dump())
    except Exception:
        logger.exception("population failed")
        return ApiResponse(success=False, error="Form population failed. Check server logs.")


_ARTIFACT_MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png"}


@app.get("/api/population-artifact/{artifact_id}")
async def population_artifact(artifact_id: str, download: bool = False):
    """Serve the captured filled-form artifact (PDF or PNG).

    Inline by default so the browser renders it in a tab; ``?download=1``
    switches to attachment. The id is a bare content hash; anything else
    resolves to None inside stored_artifact_path, so no path input ever
    reaches the filesystem.
    """
    path = stored_artifact_path(artifact_id)
    if path is None:
        return JSONResponse(
            status_code=404,
            content=ApiResponse(
                success=False, error="No such artifact. Populate the form first."
            ).model_dump(),
        )
    return FileResponse(
        path,
        media_type=_ARTIFACT_MEDIA_TYPES[path.suffix],
        filename=f"a28-filled{path.suffix}",
        content_disposition_type="attachment" if download else "inline",
    )


class TelemetryEvent(BaseModel):
    """UI event from the frontend. Names are namespaced and metadata values
    are scalar-only so nothing free-form (or PII-shaped) can be relayed."""

    name: str = Field(min_length=4, max_length=64, pattern=r"^ui\.[a-z0-9_.]+$")
    session_id: str | None = Field(None, max_length=64)
    metadata: dict[str, TelemetryValue] = Field(default_factory=dict)


@app.post("/api/telemetry")
async def telemetry(event: TelemetryEvent) -> ApiResponse:
    """Relay a frontend event into the trace timeline (no-op when disabled)."""
    trimmed = {
        key[:40]: (value[:200] if isinstance(value, str) else value)
        for key, value in list(event.metadata.items())[:20]
    }
    recorded = record_frontend_event(event.name, event.session_id, trimmed)
    return ApiResponse(success=True, data={"recorded": recorded})
