"""Input ingestion: magic-byte format sniffing, EXIF-aware image loading,
and per-page PDF rendering via PyMuPDF.

Format is decided ONLY by magic bytes — extension and client MIME type are
never trusted (see CLAUDE.md guardrails).
"""
import io
import logging
from typing import Literal

import fitz  # PyMuPDF
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings, get_settings

logger = logging.getLogger("yunaki.extraction.render")

SniffedFormat = Literal["pdf", "png", "jpeg"]

_MAGIC_BYTES: tuple[tuple[SniffedFormat, bytes], ...] = (
    ("pdf", b"%PDF"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpeg", b"\xff\xd8\xff"),
)

# Longest-side cap for direct image uploads, derived from the PDF render DPI:
# 20 inches at render_dpi (4400 px at the default 220 DPI). Anything larger is
# an enormous scan that only slows the vision call down; anything at or below
# passes through at native resolution because detail matters for OCR.
_MAX_SIDE_INCHES = 20


def max_image_side(settings: Settings) -> int:
    return settings.render_dpi * _MAX_SIDE_INCHES


def sniff_format(file_bytes: bytes, settings: Settings | None = None) -> SniffedFormat:
    """Identify the payload by magic bytes. Raises ValueError for anything else."""
    settings = settings or get_settings()
    for fmt, magic in _MAGIC_BYTES:
        if file_bytes.startswith(magic):
            return fmt
    accepted = ", ".join(f.upper() for f in settings.allowed_formats)
    raise ValueError(
        f"Unrecognized file format. Please upload one of: {accepted}. "
        "The file contents did not match any accepted format."
    )


def prepare_pages(file_bytes: bytes, settings: Settings | None = None) -> list[Image.Image]:
    """Turn an upload into a list of RGB page images ready for the vision call.

    Images (JPEG/PNG) → one EXIF-corrected image, downscaled only if enormous.
    PDFs → every page rendered at settings.render_dpi, capped at max_pdf_pages.
    """
    settings = settings or get_settings()
    fmt = sniff_format(file_bytes, settings)
    if fmt == "pdf":
        return _render_pdf(file_bytes, settings)
    return [_load_image(file_bytes, settings)]


def to_png_bytes(image: Image.Image) -> bytes:
    """Encode a page image as PNG (lossless) for the vision API."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _load_image(file_bytes: bytes, settings: Settings) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        logger.warning("image decode failed: %s", exc)
        raise ValueError(
            "The image file could not be decoded — it appears to be corrupted. "
            "Please re-export or re-scan it and upload again."
        ) from exc

    oriented = ImageOps.exif_transpose(image) or image
    rgb = oriented.convert("RGB")

    cap = max_image_side(settings)
    longest = max(rgb.size)
    if longest > cap:
        scale = cap / longest
        new_size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        logger.info("downscaling enormous image %sx%s -> %sx%s", rgb.width, rgb.height, *new_size)
        rgb = rgb.resize(new_size, Image.Resampling.LANCZOS)
    return rgb


def _render_pdf(file_bytes: bytes, settings: Settings) -> list[Image.Image]:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        logger.warning("pdf open failed: %s", exc)
        raise ValueError(
            "The PDF could not be opened — it appears to be corrupted or invalid. "
            "Please re-export it and upload again."
        ) from exc

    try:
        if doc.needs_pass:
            raise ValueError(
                "The PDF is password-protected. Please remove the password and upload again."
            )
        page_count = doc.page_count
        if page_count == 0:
            raise ValueError("The PDF contains no pages.")
        if page_count > settings.max_pdf_pages:
            raise ValueError(
                f"The PDF has {page_count} pages, which exceeds the "
                f"{settings.max_pdf_pages}-page limit. Please upload only the "
                "pages of the document itself."
            )

        zoom = settings.render_dpi / 72  # PDF user space is 72 DPI
        matrix = fitz.Matrix(zoom, zoom)
        pages: list[Image.Image] = []
        for page in doc:
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
        logger.info("rendered pdf: %d page(s) at %d dpi", page_count, settings.render_dpi)
        return pages
    finally:
        doc.close()
