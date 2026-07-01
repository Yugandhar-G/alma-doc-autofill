"""Extraction prompt contract. This text is a graded design artifact —
change only with explicit approval (see CLAUDE.md governance)."""
from app.schemas.common import DocType

_DOC_LABEL: dict[DocType, str] = {
    "passport": "passport",
    "g28": "Form G-28 (Notice of Entry of Appearance as Attorney or Accredited Representative)",
}

_CONTRACT = """You are extracting structured data from a {doc_label} image.
Return JSON matching the provided schema exactly.

Rules:
1. If a field is absent, blank, marked "N/A", "None", or illegible → null.
2. Never guess, infer, or complete partial values. A null is correct;
   a plausible guess is a defect.
3. Normalize at extraction time: dates → YYYY-MM-DD, country → full
   English name, US state → full name, sex → single letter M/F/X.
4. Transcribe names exactly as printed, including diacritics.
5. Also report `document_type_detected`: what kind of document the image
   actually shows ("passport", "g28", or "other") — regardless of what
   was requested.
6. Output JSON only. No prose, no markdown fences.
"""


def extraction_prompt(doc_type: DocType) -> str:
    return _CONTRACT.format(doc_label=_DOC_LABEL[doc_type])
