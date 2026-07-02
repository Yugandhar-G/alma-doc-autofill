"""Supabase DocumentStore: originals in a Storage bucket, extraction JSON in
the `extractions` table (see supabase_schema.sql for one-time setup).

The supabase-py client is synchronous, so every call is pushed off the event
loop via asyncio.to_thread. Misconfigured credentials fail LOUD with an
actionable message — never silently fall back to local disk.

PII rule: original filenames may contain names, so they are never persisted
or logged; documents are referenced by content hash only.
"""
import asyncio
import logging
from hashlib import sha256

from supabase import Client, create_client

from app.config import Settings
from app.schemas import ExtractionEnvelope
from app.storage.base import DocumentStore

logger = logging.getLogger("alma.storage.supabase")

_EXTRACTIONS_TABLE = "extractions"

_MAGIC_TYPES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF", "pdf", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)


def _sniff(content: bytes) -> tuple[str, str]:
    for magic, extension, mime in _MAGIC_TYPES:
        if content.startswith(magic):
            return extension, mime
    return "bin", "application/octet-stream"


class SupabaseError(RuntimeError):
    """Raised when Supabase is configured but an operation fails."""


class SupabaseStore(DocumentStore):
    def __init__(self, settings: Settings) -> None:
        if not (settings.supabase_url and settings.supabase_service_key):
            raise SupabaseError(
                "SupabaseStore requires SUPABASE_URL and SUPABASE_SERVICE_KEY. "
                "Unset both to fall back to local-disk storage."
            )
        try:
            self._client: Client = create_client(
                settings.supabase_url, settings.supabase_service_key
            )
        except Exception as exc:
            raise SupabaseError(
                "Could not initialize the Supabase client. Check that SUPABASE_URL "
                f"and SUPABASE_SERVICE_KEY in backend/.env are correct. Cause: {exc}"
            ) from exc
        self._bucket = settings.supabase_bucket

    async def save_document(self, content: bytes, doc_type: str, filename: str) -> str:
        doc_id = sha256(content).hexdigest()
        extension, mime = _sniff(content)
        path = f"{doc_type}/{doc_id}.{extension}"

        def _upload() -> None:
            self._client.storage.from_(self._bucket).upload(
                path, content, file_options={"content-type": mime, "upsert": "true"}
            )

        try:
            await asyncio.to_thread(_upload)
        except Exception as exc:
            raise SupabaseError(
                f"Supabase Storage upload failed (bucket {self._bucket!r}, doc "
                f"{doc_id}). Verify the bucket exists and the service key is valid "
                f"— see app/storage/supabase_schema.sql. Cause: {exc}"
            ) from exc
        logger.info("stored document doc_type=%s doc_id=%s", doc_type, doc_id)
        return doc_id

    async def save_extraction(
        self, doc_id: str, envelope: ExtractionEnvelope, kind: str = "raw"
    ) -> None:
        row = {
            "doc_id": doc_id,
            "doc_type": envelope.document_type_requested,
            "kind": kind,
            "envelope": envelope.model_dump(mode="json"),
        }

        def _upsert() -> None:
            self._client.table(_EXTRACTIONS_TABLE).upsert(
                row, on_conflict="doc_id,doc_type,kind"
            ).execute()

        try:
            await asyncio.to_thread(_upsert)
        except Exception as exc:
            raise SupabaseError(
                f"Supabase insert into {_EXTRACTIONS_TABLE!r} failed (doc {doc_id}). "
                "Verify the table exists — see app/storage/supabase_schema.sql. "
                f"Cause: {exc}"
            ) from exc
        logger.info("stored extraction doc_id=%s", doc_id)

    async def get_extraction(
        self, doc_id: str, doc_type: str, kind: str = "raw"
    ) -> ExtractionEnvelope | None:
        def _select() -> list[dict]:
            response = (
                self._client.table(_EXTRACTIONS_TABLE)
                .select("envelope")
                .eq("doc_id", doc_id)
                .eq("doc_type", doc_type)
                .eq("kind", kind)
                .limit(1)
                .execute()
            )
            return response.data or []

        try:
            rows = await asyncio.to_thread(_select)
        except Exception as exc:
            raise SupabaseError(
                f"Supabase read from {_EXTRACTIONS_TABLE!r} failed (doc {doc_id}). "
                f"Cause: {exc}"
            ) from exc
        if not rows:
            return None
        return ExtractionEnvelope.model_validate(rows[0]["envelope"])
