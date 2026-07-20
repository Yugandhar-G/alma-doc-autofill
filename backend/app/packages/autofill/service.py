"""Slot extraction service — the boundary work shared by the legacy
/api/extract endpoint and the package run endpoint: capped reads, guardrail
rejection per slot, passport front/back merge, coherence warnings, raw+final
audit persistence. Moved out of main.py so HTTP handlers stay thin.

PII rule unchanged: response payloads carry extracted values by design; logs
reference documents by content hash only.
"""
import logging

from fastapi import UploadFile

from app.config import get_settings
from app.extraction import check_coherence, extract_document
from app.merge import merge_passport_envelopes
from app.schemas import DocType, ExtractionEnvelope, FieldWarning, G28Data, PassportData
from app.storage.base import get_store

logger = logging.getLogger("yunaki.autofill.service")

STORAGE_WARNING = FieldWarning(
    field="storage",
    message="The extraction could not be persisted to storage; results are "
    "shown but no audit record was saved.",
)


async def read_capped(upload: UploadFile) -> bytes | None:
    """Read an upload without buffering past the size cap (Content-Length is
    checked first, then enforced while chunk-reading in case the header lies)."""
    max_bytes = get_settings().max_file_mb * 1024 * 1024
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


async def _persist_raw(
    store, content: bytes, doc_type: DocType, filename: str, envelope: ExtractionEnvelope
) -> None:
    doc_id = await store.save_document(content, doc_type, filename)
    await store.save_extraction(doc_id, envelope, kind="raw")


async def persist_final(envelope_dump: dict, doc_id: str | None, label: str) -> None:
    """Persist the record the reviewer actually sees (post-merge/coherence)."""
    if doc_id is None:
        return
    store = get_store()
    envelope = ExtractionEnvelope.model_validate(envelope_dump)
    await _save_guarded(
        store.save_extraction(doc_id, envelope, kind="final"), f"{label} final"
    )


async def extract_one(
    upload: UploadFile, doc_type: DocType
) -> tuple[ExtractionEnvelope | dict, str | None]:
    """Extract one uploaded file → (envelope | {"error": ...}, doc_id).

    Guardrail rejections come back as {"error": ...} so the frontend can pin
    them to the offending slot. Storage failures degrade to a warning on the
    envelope — a working extraction is never discarded over persistence.
    """
    settings = get_settings()
    content = await read_capped(upload)
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
            update={"warnings": [*envelope.warnings, STORAGE_WARNING]}
        )
    return envelope, doc_id


def attach_coherence_warnings(data: dict) -> None:
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


async def extract_slots(
    passport_front: UploadFile | None,
    passport_back: UploadFile | None,
    g28: UploadFile | None,
) -> dict:
    """The full slot pipeline main.py's /api/extract has always run: per-slot
    extraction with isolation, front/back merge (front authoritative),
    coherence warnings, final-audit persistence. Returns the slot dict the
    reviewer consumes (envelope dumps or {"error": ...} per slot)."""
    data: dict = {}

    if passport_back is not None and passport_front is None:
        data["passport_back"] = {
            "error": "Not processed — upload the passport front (photo page) "
            "along with the back."
        }

    front_doc_id: str | None = None
    if passport_front is not None:
        front, front_doc_id = await extract_one(passport_front, "passport")
        if isinstance(front, dict):  # front rejected → slot error, no merge
            data["passport"] = front
            if passport_back is not None:
                data["passport_back"] = {
                    "error": "Not processed — the front side was rejected."
                }
        else:
            back: ExtractionEnvelope | None = None
            if passport_back is not None:
                back_result, _ = await extract_one(passport_back, "passport")
                if isinstance(back_result, dict):
                    data["passport_back"] = back_result
                else:
                    back = back_result
            data["passport"] = merge_passport_envelopes(front, back).model_dump()

    g28_doc_id: str | None = None
    if g28 is not None:
        g28_result, g28_doc_id = await extract_one(g28, "g28")
        data["g28"] = (
            g28_result if isinstance(g28_result, dict) else g28_result.model_dump()
        )

    attach_coherence_warnings(data)

    # Audit trail of what the reviewer is shown (raw records saved above).
    if isinstance(data.get("passport"), dict) and "error" not in data["passport"]:
        await persist_final(data["passport"], front_doc_id, "passport")
    if isinstance(data.get("g28"), dict) and "error" not in data["g28"]:
        await persist_final(data["g28"], g28_doc_id, "g28")

    return data
