"""Shared test helpers: synthetic images/PDFs built in-memory so the offline
unit tests need no fixture files, no network, and no API key."""
import io

import fitz
import numpy as np
import pytest
from PIL import Image

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Isolated Settings with defaults — never the lru-cached app instance."""
    return Settings(_env_file=None)


def make_noise_image(width: int, height: int, seed: int = 7) -> Image.Image:
    """High-frequency noise → very sharp by variance-of-Laplacian."""
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    return Image.fromarray(pixels, mode="RGB")


def make_flat_image(width: int, height: int, value: int = 128) -> Image.Image:
    """Uniform gray → zero Laplacian variance (maximally blurry)."""
    pixels = np.full((height, width, 3), value, dtype=np.uint8)
    return Image.fromarray(pixels, mode="RGB")


def image_bytes(image: Image.Image, fmt: str, **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


PDF_PAGE_WIDTH_PT = 612  # US letter
PDF_PAGE_HEIGHT_PT = 792


def make_pdf_bytes(pages: int, text: str = "alma test page") -> bytes:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=PDF_PAGE_WIDTH_PT, height=PDF_PAGE_HEIGHT_PT)
        page.insert_text((72, 72), f"{text} {index + 1}")
    data = doc.tobytes()
    doc.close()
    return data
