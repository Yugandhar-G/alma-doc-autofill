"""Pre-LLM quality gate: resolution and blur checks, applied per page/image.

Rejecting a bad scan before the vision call is cheaper and more honest than
letting the model hallucinate over an unreadable image.
"""
import logging

import numpy as np
from PIL import Image

from app.config import Settings, get_settings

logger = logging.getLogger("alma.extraction.quality")


def variance_of_laplacian(gray: np.ndarray) -> float:
    """Sharpness metric: variance of the 4-neighbour Laplacian (pure numpy).

    Blurred images have weak edges, so the Laplacian response is nearly flat
    and its variance collapses toward zero.
    """
    g = gray.astype(np.float64)
    laplacian = (
        g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4.0 * g[1:-1, 1:-1]
    )
    return float(laplacian.var())


def assert_page_quality(
    image: Image.Image, page_label: str, settings: Settings | None = None
) -> None:
    """Raise ValueError with a re-scan instruction when a page fails the gate."""
    settings = settings or get_settings()

    shorter_side = min(image.size)
    if shorter_side < settings.min_image_dimension:
        raise ValueError(
            f"{page_label} is too low-resolution ({image.width}x{image.height} px; "
            f"the shorter side must be at least {settings.min_image_dimension} px). "
            "Please re-scan or re-photograph the document at a higher resolution."
        )

    gray = np.asarray(image.convert("L"))
    sharpness = variance_of_laplacian(gray)
    if sharpness < settings.blur_threshold:
        logger.info("%s rejected: sharpness %.2f < %.2f", page_label, sharpness, settings.blur_threshold)
        raise ValueError(
            f"{page_label} is too blurry to read reliably. "
            "Please re-scan or re-photograph the document in focus and upload again."
        )
