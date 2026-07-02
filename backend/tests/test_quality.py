"""Offline tests for the pre-LLM quality gate (resolution + blur)."""
import numpy as np
import pytest

from app.config import Settings
from app.extraction.quality import assert_page_quality, variance_of_laplacian
from tests.conftest import make_flat_image, make_noise_image


class TestVarianceOfLaplacian:
    def test_flat_image_scores_zero(self) -> None:
        gray = np.asarray(make_flat_image(100, 100).convert("L"))
        assert variance_of_laplacian(gray) == 0.0

    def test_noise_scores_high(self) -> None:
        gray = np.asarray(make_noise_image(100, 100).convert("L"))
        assert variance_of_laplacian(gray) > 1000.0


class TestQualityGate:
    def test_sharp_large_image_passes(self, settings: Settings) -> None:
        image = make_noise_image(settings.min_image_dimension + 100,
                                 settings.min_image_dimension + 100)
        assert_page_quality(image, "Page 1", settings)  # must not raise

    def test_low_resolution_rejected(self, settings: Settings) -> None:
        short = settings.min_image_dimension - 1
        image = make_noise_image(2000, short)  # shorter side under the bound
        with pytest.raises(ValueError, match="re-scan or re-photograph"):
            assert_page_quality(image, "Page 1", settings)

    def test_blurry_image_rejected(self, settings: Settings) -> None:
        size = settings.min_image_dimension + 100
        image = make_flat_image(size, size)
        with pytest.raises(ValueError, match="too blurry"):
            assert_page_quality(image, "Page 2", settings)

    def test_page_label_appears_in_message(self, settings: Settings) -> None:
        size = settings.min_image_dimension + 100
        with pytest.raises(ValueError, match="Page 3"):
            assert_page_quality(make_flat_image(size, size), "Page 3", settings)

    def test_thresholds_come_from_settings(self, settings: Settings) -> None:
        lenient = settings.model_copy(update={"blur_threshold": 0.0,
                                              "min_image_dimension": 10})
        image = make_flat_image(50, 50)
        assert_page_quality(image, "Page 1", lenient)  # passes with relaxed gate
