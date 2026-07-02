"""FastAPI app — integration layer. Owns HTTP concerns only;
extraction/population/storage logic lives in the respective planes."""
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


async def _extract_one(upload: UploadFile, doc_type: DocType) -> ExtractionEnvelope | dict:
    """Extract one uploaded file. Guardrail rejections come back as
    {"error": ...} so the frontend can pin them to the offending slot."""
    content = await upload.read()
    max_bytes = settings.max_file_mb * 1024 * 1024
    if len(content) > max_bytes:
        return {"error": f"File exceeds the {settings.max_file_mb} MB limit."}
    try:
        envelope = await extract_document(content, upload.filename or "", doc_type)
    except ValueError as exc:  # guardrail rejection — user-actionable, re-upload
        return {"error": str(exc)}
    store = get_store()
    doc_id = await store.save_document(content, doc_type, upload.filename or "")
    await store.save_extraction(doc_id, envelope)
    return envelope


@app.post("/api/extract")
async def extract(
    passport_front: UploadFile | None = None,
    passport_back: UploadFile | None = None,
    g28: UploadFile | None = None,
) -> ApiResponse:
    """Extract whichever documents were uploaded.

    Passport front and back are extracted separately and merged server-side
    (front authoritative, back fills nulls). A back without a front is
    rejected — the front carries the machine-readable data.
    """
    if passport_front is None and g28 is None:
        return ApiResponse(
            success=False,
            error="Upload at least a passport front or a G-28.",
        )
    if passport_back is not None and passport_front is None:
        return ApiResponse(
            success=False,
            error="A passport back side was uploaded without a front side.",
        )
    try:
        data: dict = {}
        if passport_front is not None:
            front = await _extract_one(passport_front, "passport")
            if isinstance(front, dict):  # front rejected → slot error, no merge
                data["passport"] = front
            else:
                back: ExtractionEnvelope | None = None
                if passport_back is not None:
                    back_result = await _extract_one(passport_back, "passport")
                    if isinstance(back_result, dict):
                        data["passport_back"] = back_result
                    else:
                        back = back_result
                data["passport"] = merge_passport_envelopes(front, back).model_dump()
        if g28 is not None:
            g28_result = await _extract_one(g28, "g28")
            data["g28"] = (
                g28_result if isinstance(g28_result, dict) else g28_result.model_dump()
            )

        _attach_coherence_warnings(data)
        return ApiResponse(success=True, data=data)
    except NotImplementedError as exc:
        return ApiResponse(success=False, error=str(exc))
    except RuntimeError as exc:  # model/config failures — message is user-safe
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
    except NotImplementedError as exc:
        return ApiResponse(success=False, error=str(exc))
    except Exception:
        logger.exception("population failed")
        return ApiResponse(success=False, error="Form population failed. Check server logs.")
