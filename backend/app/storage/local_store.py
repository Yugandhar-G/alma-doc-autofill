"""Local-disk DocumentStore: the zero-config fallback when Supabase creds
are absent. Files live under settings.local_storage_dir, keyed by content
hash (which doubles as the doc_id); extraction records are keyed by
(doc_id, doc_type, kind) so identical bytes in two slots never clobber
each other's audit record. Disk I/O runs off the event loop.
"""
import asyncio
import logging
import re
from hashlib import sha256
from pathlib import Path

from app.config import Settings
from app.schemas import ExtractionEnvelope
from app.storage.base import DocumentStore, ExtractionKind

logger = logging.getLogger("yunaki.storage.local")

_DOC_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Content-sniffed extensions for stored originals (mirror of render._MAGIC_BYTES;
# unknown payloads are stored as .bin rather than rejected — the extraction
# plane, not storage, owns format enforcement).
_MAGIC_EXTENSIONS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


def _extension_for(content: bytes) -> str:
    for magic, extension in _MAGIC_EXTENSIONS:
        if content.startswith(magic):
            return extension
    return "bin"


def _require_valid_doc_id(doc_id: str) -> str:
    """doc_ids are SHA-256 hex; reject anything else (also blocks path traversal)."""
    if not _DOC_ID_PATTERN.fullmatch(doc_id):
        raise ValueError(f"Invalid doc_id: expected 64-char SHA-256 hex, got {doc_id!r}")
    return doc_id


class LocalStore(DocumentStore):
    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.local_storage_dir)

    def _extraction_path(self, doc_id: str, doc_type: str, kind: str) -> Path:
        return self._root / f"{doc_id}.{doc_type}.{kind}.extraction.json"

    async def save_document(self, content: bytes, doc_type: str, filename: str) -> str:
        doc_id = sha256(content).hexdigest()
        path = self._root / f"{doc_id}.{_extension_for(content)}"

        def _write() -> None:
            self._root.mkdir(parents=True, exist_ok=True)
            if not path.exists():  # content-addressed → identical bytes are a no-op
                path.write_bytes(content)

        await asyncio.to_thread(_write)
        logger.info("stored document doc_type=%s doc_id=%s", doc_type, doc_id)
        return doc_id

    async def save_extraction(
        self, doc_id: str, envelope: ExtractionEnvelope, kind: ExtractionKind = "raw"
    ) -> None:
        _require_valid_doc_id(doc_id)
        path = self._extraction_path(doc_id, envelope.document_type_requested, kind)
        payload = envelope.model_dump_json(indent=2)

        def _write() -> None:
            self._root.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")

        await asyncio.to_thread(_write)
        logger.info("stored extraction doc_id=%s kind=%s", doc_id, kind)

    async def get_extraction(
        self, doc_id: str, doc_type: str, kind: ExtractionKind = "raw"
    ) -> ExtractionEnvelope | None:
        _require_valid_doc_id(doc_id)
        path = self._extraction_path(doc_id, doc_type, kind)

        def _read() -> str | None:
            return path.read_text(encoding="utf-8") if path.exists() else None

        raw = await asyncio.to_thread(_read)
        return None if raw is None else ExtractionEnvelope.model_validate_json(raw)
