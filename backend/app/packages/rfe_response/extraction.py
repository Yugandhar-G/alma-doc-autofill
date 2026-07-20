"""RFE-notice extraction: upload bytes → guardrails → Gemini vision → RfeNotice.

Same ingestion + guardrail stack as passport/G-28 and evidence extraction
(magic-byte sniff, page cap, resolution/blur gate via render + quality), same
PII log rule (content hash only, never notice text). One structured vision call
returns the notice AND its grounds together (no second LLM call) — grounds are
part of the RfeNotice response schema.

make_client / call_gemini are imported at module level so tests and the offline
eval can patch this seam and inject synthetic notices without a key or network.
"""
import hashlib
import logging

from app.config import get_settings
from app.extraction import render
from app.extraction.quality import assert_page_quality
from app.kernel.llm import call_gemini, make_client
from app.packages.rfe_response.prompts import EXTRACTION_PROMPT
from app.packages.rfe_response.schemas import RfeNotice

logger = logging.getLogger("yunaki.rfe_response.extraction")


async def extract_notice_document(file_bytes: bytes, filename: str) -> RfeNotice:
    """Extract one RFE notice into an RfeNotice. Raises ValueError for guardrail
    rejections (user-actionable) and RuntimeError for model failures.

    Temperature 0 and the one-retry contract come from app.kernel.llm.call_gemini
    (settings.extraction_temperature / extraction_max_retries)."""
    settings = get_settings()
    source_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.info(
        "rfe notice extraction start source_hash=%s size_bytes=%d",
        source_hash, len(file_bytes),
    )

    pages = render.prepare_pages(file_bytes, settings)
    for index, page in enumerate(pages, start=1):
        assert_page_quality(page, f"Page {index}", settings)
    png_pages = [render.to_png_bytes(page) for page in pages]

    notice: RfeNotice = await call_gemini(  # type: ignore[assignment]
        make_client(settings),
        settings.gemini_model,
        EXTRACTION_PROMPT,
        RfeNotice,
        settings,
        png_pages=png_pages,
        source_ref=source_hash,
        trace_name="gemini.rfe_response.extract_notice",
    )
    logger.info(
        "rfe notice extraction done source_hash=%s grounds=%d deadline_present=%s pages=%d",
        source_hash, len(notice.grounds), notice.response_deadline is not None, len(pages),
    )
    return notice
