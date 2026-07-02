"""FastAPI app — integration layer. Owns HTTP concerns only;
extraction/population/storage logic lives in the respective planes.

PII rule: request/response bodies carry extracted values by design; logs
never do — documents are referenced by content hash only.
"""
import logging

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from app.extraction import check_coherence, extract_document
from app.merge import merge_passport_envelopes
from app.population import populate_form
from app.schemas import (
    ApiResponse,
    DocType,
    ExtractionEnvelope,
    FieldWarning,
    G28Data,
    PassportData,
)
from app.storage.base import get_store

logger = logging.getLogger("alma")
settings = get_settings()

app = FastAPI(title="alma-doc-autofill")
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
async def populate(req: PopulateRequest) -> ApiResponse:
    if req.passport is None and req.g28 is None:
        return ApiResponse(success=False, error="Nothing to populate.")
    try:
        report = await populate_form(req.passport, req.g28, headed=req.headed)
        return ApiResponse(success=True, data=report.model_dump())
    except Exception:
        logger.exception("population failed")
        return ApiResponse(success=False, error="Form population failed. Check server logs.")
