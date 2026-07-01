"""Extraction engine — implemented by Agent A per the interface contract
in __init__.py. This stub keeps the API importable until then."""
from app.schemas import DocType, ExtractionEnvelope


async def extract_document(
    file_bytes: bytes, filename: str, doc_type: DocType
) -> ExtractionEnvelope:
    raise NotImplementedError("extraction engine not implemented yet (Agent A)")
