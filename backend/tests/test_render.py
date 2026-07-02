"""Offline tests for ingestion: magic-byte sniffing, PDF rendering, caps."""
import pytest
from PIL import Image

from app.config import Settings
from app.extraction import render
from tests.conftest import image_bytes, make_noise_image, make_pdf_bytes


class TestSniffFormat:
    def test_pdf_magic(self, settings: Settings) -> None:
        assert render.sniff_format(make_pdf_bytes(1), settings) == "pdf"

    def test_png_magic(self, settings: Settings) -> None:
        data = image_bytes(make_noise_image(10, 10), "PNG")
        assert render.sniff_format(data, settings) == "png"

    def test_jpeg_magic(self, settings: Settings) -> None:
        data = image_bytes(make_noise_image(10, 10), "JPEG")
        assert render.sniff_format(data, settings) == "jpeg"

    def test_extension_is_ignored_content_wins(self, settings: Settings) -> None:
        # A "renamed .jpg" that is actually a PDF must sniff as PDF.
        assert render.sniff_format(make_pdf_bytes(1), settings) == "pdf"

    @pytest.mark.parametrize(
        "payload",
        [b"", b"GIF89a...", b"<html></html>", b"\x00\x01\x02\x03"],
        ids=["empty", "gif", "html", "binary-junk"],
    )
    def test_unknown_format_rejected_with_accepted_list(
        self, settings: Settings, payload: bytes
    ) -> None:
        with pytest.raises(ValueError, match="PDF, JPEG, PNG"):
            render.sniff_format(payload, settings)


class TestPdfRendering:
    def test_renders_every_page(self, settings: Settings) -> None:
        pages = render.prepare_pages(make_pdf_bytes(3), settings)
        assert len(pages) == 3
        assert all(isinstance(page, Image.Image) for page in pages)

    def test_render_dpi_respected(self, settings: Settings) -> None:
        # Test PDF pages are 612x792 pt (US letter). At render_dpi the pixel
        # size must scale by dpi/72.
        from tests.conftest import PDF_PAGE_WIDTH_PT

        (page,) = render.prepare_pages(make_pdf_bytes(1), settings)
        expected_width = round(PDF_PAGE_WIDTH_PT * settings.render_dpi / 72)
        assert abs(page.width - expected_width) <= 2

    def test_page_cap_enforced(self, settings: Settings) -> None:
        capped = settings.model_copy(update={"max_pdf_pages": 2})
        with pytest.raises(ValueError, match="2-page limit"):
            render.prepare_pages(make_pdf_bytes(3), capped)

    def test_corrupt_pdf_rejected(self, settings: Settings) -> None:
        with pytest.raises(ValueError, match="corrupted or invalid"):
            render.prepare_pages(b"%PDF-1.7 this is not really a pdf", settings)


class TestImageLoading:
    def test_image_passes_through_at_native_resolution(self, settings: Settings) -> None:
        data = image_bytes(make_noise_image(800, 600), "JPEG")
        (page,) = render.prepare_pages(data, settings)
        assert page.size == (800, 600)

    def test_exif_orientation_applied(self, settings: Settings) -> None:
        image = make_noise_image(300, 200)
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 CW on display
        data = image_bytes(image, "JPEG", exif=exif)
        (page,) = render.prepare_pages(data, settings)
        assert page.size == (200, 300)  # dimensions swapped by orientation fix

    def test_enormous_image_downscaled_to_bound(self, settings: Settings) -> None:
        bound = render.max_image_side(settings)
        data = image_bytes(make_noise_image(bound + 600, 500), "JPEG")
        (page,) = render.prepare_pages(data, settings)
        assert max(page.size) == bound

    def test_corrupt_image_rejected(self, settings: Settings) -> None:
        truncated = image_bytes(make_noise_image(100, 100), "JPEG")[:40]
        with pytest.raises(ValueError, match="corrupted"):
            render.prepare_pages(truncated, settings)
