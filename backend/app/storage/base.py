"""Storage interface — Supabase when configured, local disk otherwise.
Concrete implementations by Agent A. Exactly three methods; keep it that way."""
from abc import ABC, abstractmethod

from app.schemas import ExtractionEnvelope


class DocumentStore(ABC):
    @abstractmethod
    async def save_document(self, content: bytes, doc_type: str, filename: str) -> str:
        """Persist original bytes; returns doc_id (content hash)."""

    @abstractmethod
    async def save_extraction(self, doc_id: str, envelope: ExtractionEnvelope) -> None:
        """Persist the extraction result for a document."""

    @abstractmethod
    async def get_extraction(self, doc_id: str) -> ExtractionEnvelope | None:
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
