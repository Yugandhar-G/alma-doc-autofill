"""Filled-form artifact: a downloadable/shareable record of the populated A-28.

Captured after the verify pass, before the browser closes — otherwise the
filled form vanishes with the window and only the JSON report survives.
Headless Chromium prints the page to a real PDF; headed Chromium cannot
(CDP printToPDF is headless-only), so headed runs fall back to a full-page
PNG screenshot.

Artifacts land on local disk under settings.local_storage_dir, keyed by
content hash like every other stored blob — the id is PII-safe to log and
safe to place in a URL.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Literal

from playwright.async_api import Page

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ArtifactKind = Literal["pdf", "png"]

_ARTIFACT_ID = re.compile(r"[0-9a-f]{64}")
_SUBDIR = "artifacts"
_KINDS: tuple[ArtifactKind, ...] = ("pdf", "png")


def _artifact_dir(settings: Settings) -> Path:
    return Path(settings.local_storage_dir) / _SUBDIR


async def capture_artifact(page: Page, headed: bool) -> tuple[bytes, ArtifactKind]:
    """Snapshot the current page state as downloadable bytes."""
    if headed:
        return await page.screenshot(full_page=True, type="png"), "png"
    return await page.pdf(print_background=True), "pdf"


def save_artifact(
    data: bytes, kind: ArtifactKind, settings: Settings | None = None
) -> str:
    """Persist artifact bytes; returns the content-hash id."""
    settings = settings or get_settings()
    artifact_id = hashlib.sha256(data).hexdigest()
    directory = _artifact_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{artifact_id}.a28.{kind}").write_bytes(data)
    logger.info("saved population artifact %s (%s, %d bytes)", artifact_id, kind, len(data))
    return artifact_id


def stored_artifact_path(
    artifact_id: str, settings: Settings | None = None
) -> Path | None:
    """Resolve an artifact id to its file, or None.

    Rejects anything that is not exactly a lowercase hex content hash, so
    ids can be taken straight from a URL path segment without traversal risk.
    """
    if not _ARTIFACT_ID.fullmatch(artifact_id):
        return None
    settings = settings or get_settings()
    directory = _artifact_dir(settings)
    for kind in _KINDS:
        candidate = directory / f"{artifact_id}.a28.{kind}"
        if candidate.exists():
            return candidate
    return None
