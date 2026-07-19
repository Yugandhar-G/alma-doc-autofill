"""Evidence-document extraction: upload bytes → guardrails → Gemini vision →
EvidenceDocRecord with VERBATIM key-fact excerpts.

Excerpts must be verbatim because the citation audit substring-checks every
doc citation against them — a paraphrase here would make honest citations
unverifiable downstream. Same guardrail stack as passport/G-28 extraction
(magic bytes, page cap, resolution, blur), same PII log rule (hashes only).
"""
import hashlib
import logging
from typing import Literal

from pydantic import BaseModel, Field, create_model

from app.config import get_settings
from app.extraction import render
from app.extraction.quality import assert_page_quality
from app.llm import call_gemini
from app.schemas import EvidenceDocRecord, EvidenceKind, FieldWarning
from app.kernel.llm import make_client

logger = logging.getLogger("yunaki.screener.evidence")

EVIDENCE_PROMPT = """You are extracting evidence for a USCIS extraordinary-ability
screening (O-1A / EB-1A). Read the attached document and return JSON.

RULES (non-negotiable):
1. key_facts entries must be VERBATIM transcriptions of the document's most
   probative sentences or lines — names, award titles, dates, amounts,
   publication venues, role descriptions. Copy exactly, including
   capitalization and diacritics. Never paraphrase, never summarize.
2. Prefer facts that speak to USCIS criteria: awards and their scope,
   selective memberships, press about the person, judging/review activity,
   original contributions and their adoption, scholarly publication venues,
   critical roles at distinguished organizations, salary figures,
   exhibitions, commercial success.
3. Illegible or absent → omit. Never guess or complete a partial value.
4. document_kind_detected: classify what this document actually is, not what
   it was uploaded as.
5. title: the document's own title or heading, verbatim, if present.
Return JSON only."""


class EvidenceDocData(BaseModel):
    """LLM-facing payload; converted to EvidenceDocRecord post-validation."""

    title: str | None = Field(None, max_length=300)
    key_facts: list[str] = Field(default_factory=list, max_length=30)


_KIND_LITERAL = Literal[
    "resume",
    "award",
    "press",
    "recommendation_letter",
    "publication",
    "salary_doc",
    "membership_proof",
    "patent",
    "other",
]

_WRAPPER = create_model(
    "EvidenceExtractionResponse",
    document_kind_detected=(_KIND_LITERAL, ...),
    data=(EvidenceDocData, ...),
)


async def extract_evidence_document(
    file_bytes: bytes, filename: str, expected_kind: EvidenceKind | None = None
) -> EvidenceDocRecord:
    """Extract one evidence document. Raises ValueError for guardrail
    rejections (user-actionable) and RuntimeError for model failures."""
    settings = get_settings()
    source_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.info(
        "evidence extraction start source_hash=%s size_bytes=%d expected=%s",
        source_hash, len(file_bytes), expected_kind,
    )

    pages = render.prepare_pages(file_bytes, settings)
    for index, page in enumerate(pages, start=1):
        assert_page_quality(page, f"Page {index}", settings)
    png_pages = [render.to_png_bytes(page) for page in pages]

    result = await call_gemini(
        make_client(settings),
        settings.gemini_model,
        EVIDENCE_PROMPT,
        _WRAPPER,
        settings,
        png_pages=png_pages,
        source_ref=source_hash,
        trace_name="gemini.screener.evidence",
    )

    detected: EvidenceKind = result.document_kind_detected  # type: ignore[attr-defined]
    data: EvidenceDocData = result.data  # type: ignore[attr-defined]
    warnings: list[FieldWarning] = []
    if expected_kind is not None and detected != expected_kind:
        # Mismatch is surfaced, not blocked — evidence slots are advisory,
        # unlike the passport/G-28 slots where the wrong doc halts extraction.
        warnings.append(
            FieldWarning(
                field="document_kind_detected",
                message=f"Uploaded as {expected_kind} but the file looks like "
                f"'{detected}'. Facts were extracted; review the classification.",
            )
        )

    record = EvidenceDocRecord(
        source_hash=source_hash,
        document_kind_detected=detected,
        title=data.title,
        key_facts=[fact[:500] for fact in data.key_facts if fact.strip()],
        warnings=warnings,
    )
    logger.info(
        "evidence extraction done source_hash=%s detected=%s facts=%d pages=%d",
        source_hash, detected, len(record.key_facts), len(pages),
    )
    return record
