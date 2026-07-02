"""Storage interface — Supabase when configured, local disk otherwise.
Concrete implementations by Agent A. Exactly three methods; keep it that way.

Extraction records are keyed by (doc_id, doc_type, kind) so identical bytes
uploaded into two slots cannot clobber each other's audit record, and both
the raw extraction and the reviewed/merged record the user actually saw are
retained ("raw" = straight from the model; "final" = post-merge/coherence,
what the review table displayed).
"""
from abc import ABC, abstractmethod
from typing import Literal

from app.schemas import ExtractionEnvelope

ExtractionKind = Literal["raw", "final"]


class DocumentStore(ABC):
    @abstractmethod
    async def save_document(self, content: bytes, doc_type: str, filename: str) -> str:
        """Persist original bytes; returns doc_id (content hash)."""

    @abstractmethod
    async def save_extraction(
        self, doc_id: str, envelope: ExtractionEnvelope, kind: ExtractionKind = "raw"
    ) -> None:
        """Persist an extraction record keyed by (doc_id, requested doc type, kind)."""

    @abstractmethod
    async def get_extraction(
        self, doc_id: str, doc_type: str, kind: ExtractionKind = "raw"
    ) -> ExtractionEnvelope | None:
        """Fetch a previously saved extraction, if any."""


def get_store() -> DocumentStore:
    """Factory: SupabaseStore when settings.supabase_enabled, else LocalStore."""
    from app.config import get_settings

    settings = get_settings()
    if settings.supabase_enabled:
        from .supabase_store import SupabaseStore

        return SupabaseStore(settings)
    from .local_store import LocalStore

    return LocalStore(settings)
