"""Extraction plane public interface.

Contract (implemented in engine.py — Agent A):

    async def extract_document(
        file_bytes: bytes, filename: str, doc_type: DocType
    ) -> ExtractionEnvelope

Pipeline: sniff format by magic bytes → guardrails (size, page cap,
resolution, blur) → images pass through (EXIF-rotated), PDFs render
per-page via PyMuPDF at settings.render_dpi → Gemini structured call
(prompts.extraction_prompt, temperature from settings) → Pydantic
validation into PassportData / G28Data → post-validators (ISO date,
state enum, sex enum; failures null the field and add a FieldWarning)
→ ExtractionEnvelope.
"""
from .engine import extract_document

__all__ = ["extract_document"]
