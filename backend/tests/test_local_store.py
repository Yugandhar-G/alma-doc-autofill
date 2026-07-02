"""Offline tests for the local-disk DocumentStore."""
import hashlib
from pathlib import Path

import pytest

from app.config import Settings
from app.schemas import ExtractionEnvelope, FieldWarning
from app.storage.local_store import LocalStore
from tests.conftest import image_bytes, make_noise_image, make_pdf_bytes


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    return LocalStore(Settings(_env_file=None, local_storage_dir=str(tmp_path / "uploads")))


def _envelope(source_hash: str) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="g28",
        document_type_detected="g28",
        data={"attorney": {"family_name": "Smith"}},
        warnings=[FieldWarning(field="attorney.state", message="cleared")],
        model_used="test-model",
        source_hash=source_hash,
    )


async def test_document_saved_under_content_hash(store: LocalStore, tmp_path: Path) -> None:
    content = make_pdf_bytes(1)
    doc_id = await store.save_document(content, "g28", "whatever.pdf")
    assert doc_id == hashlib.sha256(content).hexdigest()
    stored = tmp_path / "uploads" / f"{doc_id}.pdf"
    assert stored.read_bytes() == content


async def test_extension_from_content_not_filename(store: LocalStore, tmp_path: Path) -> None:
    content = image_bytes(make_noise_image(20, 20), "PNG")
    doc_id = await store.save_document(content, "passport", "lying-name.pdf")
    assert (tmp_path / "uploads" / f"{doc_id}.png").exists()


async def test_extraction_round_trip(store: LocalStore) -> None:
    content = make_pdf_bytes(1)
    doc_id = await store.save_document(content, "g28", "doc.pdf")
    saved = _envelope(doc_id)
    await store.save_extraction(doc_id, saved)
    loaded = await store.get_extraction(doc_id)
    assert loaded is not None
    assert loaded.model_dump() == saved.model_dump()


async def test_get_extraction_missing_returns_none(store: LocalStore) -> None:
    assert await store.get_extraction("0" * 64) is None


async def test_duplicate_content_is_idempotent(store: LocalStore) -> None:
    content = make_pdf_bytes(2)
    first = await store.save_document(content, "g28", "a.pdf")
    second = await store.save_document(content, "g28", "b.pdf")
    assert first == second


@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "short", "Z" * 64])
async def test_invalid_doc_id_rejected(store: LocalStore, bad_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid doc_id"):
        await store.get_extraction(bad_id)
