"""FastAPI app — integration layer. Owns HTTP concerns only;
extraction/population/storage logic lives in the respective planes."""
import logging

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from app.extraction import extract_document
from app.population import populate_form
from app.schemas import ApiResponse, G28Data, PassportData
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


async def _extract_one(upload: UploadFile, doc_type: str) -> dict:
    content = await upload.read()
    max_bytes = settings.max_file_mb * 1024 * 1024
    if len(content) > max_bytes:
        return {
            "error": f"File exceeds the {settings.max_file_mb} MB limit.",
            "document_type_requested": doc_type,
        }
    envelope = await extract_document(content, upload.filename or "", doc_type)
    store = get_store()
    doc_id = await store.save_document(content, doc_type, upload.filename or "")
    await store.save_extraction(doc_id, envelope)
    return envelope.model_dump()


@app.post("/api/extract")
async def extract(
    passport: UploadFile | None = None, g28: UploadFile | None = None
) -> ApiResponse:
    if passport is None and g28 is None:
        return ApiResponse(success=False, error="Upload at least one document.")
    try:
        data: dict = {}
        if passport is not None:
            data["passport"] = await _extract_one(passport, "passport")
        if g28 is not None:
            data["g28"] = await _extract_one(g28, "g28")
        return ApiResponse(success=True, data=data)
    except NotImplementedError as exc:
        return ApiResponse(success=False, error=str(exc))
    except ValueError as exc:  # guardrail rejections surface user-friendly
        return ApiResponse(success=False, error=str(exc))
    except Exception:
        logger.exception("extraction failed")
        return ApiResponse(success=False, error="Extraction failed. Check server logs.")


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
