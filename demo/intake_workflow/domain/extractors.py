"""Anthropic-backed document extractor + pure helpers for layer-2 checks.

Companion to app/domain/layer2.py: the frozen ``Extractor`` protocol lives
there; the concrete implementation and the small, side-effect-free helper
functions the cross-check logic leans on live here (per the module boundary:
"helpers go in app/domain/extractors.py").

Design invariants (PRINCIPLES §5 — null over guess):
- ``extract`` never raises. Any failure — unreadable file, unsupported type,
  API error, or a model response that won't validate — returns ``None`` so the
  caller flags "could not verify" instead of trusting a fabrication.
- The extraction prompt forbids guessing: an omitted/empty field is the
  correct answer whenever a value isn't literally on the page.
- Structured output only (single classification/transcription pass, no agent
  loop): this is exactly the task-shape PRINCIPLES §9 calls a direct call.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field, ValidationError

# Exactly this model id — do not substitute (frozen by the task contract).
MODEL = "claude-opus-4-8"

# Extension -> (block type, media_type) for the document content block.
_PDF = "application/pdf"
_MEDIA_TYPES: dict[str, tuple[str, str]] = {
    "pdf": ("document", _PDF),
    "png": ("image", "image/png"),
    "jpg": ("image", "image/jpeg"),
    "jpeg": ("image", "image/jpeg"),
}


class ExtractedDoc(BaseModel):
    """Structured-output schema for a single client document.

    Every field is optional: the model is instructed to omit anything not
    literally present rather than guess a plausible value.
    """

    document_type: str | None = None
    person_names: list[str] = Field(default_factory=list)
    issue_date: str | None = None
    expiry_date: str | None = None
    address: str | None = None
    notes: str | None = None


# --------------------------------------------------------------- pure helpers

def _name_tokens(name: str) -> set[str]:
    """Lowercased alphabetic name tokens, dropping single-letter initials so a
    middle initial ("Ana J Marquez") never causes a false mismatch."""
    return {t for t in re.findall(r"[a-z]+", (name or "").lower()) if len(t) > 1}


def names_match(a: str, b: str) -> bool:
    """Loose, case-insensitive, token-based name match.

    Two names match when one's token set is contained in the other's — so
    "ANA MARQUEZ" matches "Ana Marquez", and a middle name on one side
    ("Ana Sofia Marquez" vs "Ana Marquez") still matches, while genuinely
    different names ("Ana Marquez" vs "Wei Chen") do not.
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


def matches_any(candidate: str, expected: list[str]) -> bool:
    """True if ``candidate`` loosely matches at least one expected name."""
    return any(names_match(candidate, e) for e in expected)


# Words too generic to signal a document-type mismatch on their own.
_LABEL_STOPWORDS = {
    "or", "and", "with", "both", "the", "of", "for", "your", "most", "recent",
    "page", "record", "bio", "proof", "two", "any", "names", "name", "spouse",
    "petitioner", "beneficiary", "months", "statements", "statement", "policy",
    "letter", "copy", "form", "you", "our", "over", "time",
}


def _significant_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z]+", (text or "").lower())
        if len(t) > 2 and t not in _LABEL_STOPWORDS
    }


def document_type_mismatches(document_type: str, item_label: str,
                             item_description: str = "", item_category: str = "") -> bool:
    """True when an extracted ``document_type`` shares no meaningful word with
    the checklist item it was submitted against (a likely wrong-document
    upload). Conservative on purpose — only a *complete* absence of overlap
    flags, so near-synonyms ("Residential Lease" vs "Lease or deed") pass.
    """
    dt = _significant_tokens(document_type)
    kw = _significant_tokens(f"{item_label} {item_description} {item_category}")
    if not dt or not kw:
        return False
    return dt.isdisjoint(kw)


def to_plain_dict(doc: ExtractedDoc) -> dict:
    """Convert a validated ``ExtractedDoc`` to the plain dict the Extractor
    protocol documents, omitting None/empty values (null over guess)."""
    out: dict = {}
    if doc.document_type and doc.document_type.strip():
        out["document_type"] = doc.document_type.strip()
    names = [n.strip() for n in (doc.person_names or []) if n and n.strip()]
    if names:
        out["person_names"] = names
    for field in ("issue_date", "expiry_date", "address", "notes"):
        value = getattr(doc, field)
        if value and value.strip():
            out[field] = value.strip()
    return out


def build_prompt(doc_hint: str) -> str:
    """The extraction instruction. Enforces null-over-guess and names the
    expected document type so a document_type mismatch is detectable."""
    return (
        "You are helping a U.S. immigration paralegal verify a document a "
        "client uploaded for their marriage-based green card case.\n"
        f"This document is expected to be: {doc_hint}.\n\n"
        "Extract ONLY information that is literally printed on the document. "
        "Do not guess, infer, translate, or fill in a plausible value. If a "
        "field is not clearly visible, leave it empty — an omitted or null "
        "field is the correct answer whenever you are unsure.\n\n"
        "Fields:\n"
        "- document_type: what the document actually is, as printed on it "
        "(e.g. 'lease agreement', 'marriage certificate', 'passport'). Report "
        "what you truly see even if it differs from the expected type above.\n"
        "- person_names: every person's full name that appears, exactly as "
        "written. Empty list if none are legible.\n"
        "- issue_date / expiry_date: ISO YYYY-MM-DD, only if a real date is "
        "printed on the document.\n"
        "- address: the primary address printed on the document, if any.\n"
        "- notes: one short, neutral line only if something is genuinely "
        "notable; otherwise leave empty.\n"
    )


def _document_block(stored_path: str) -> dict | None:
    """Base64 content block for a PDF/image, placed before the text block.
    Returns None for an unsupported extension (caller then returns None)."""
    ext = Path(stored_path).suffix.lower().lstrip(".")
    spec = _MEDIA_TYPES.get(ext)
    if spec is None:
        return None
    block_type, media_type = spec
    with open(stored_path, "rb") as fh:
        data = fh.read()
    # b64encode emits no newlines; decode to a clean ASCII string.
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": block_type,
        "source": {"type": "base64", "media_type": media_type, "data": b64},
    }


def build_messages(stored_path: str, doc_hint: str) -> list[dict] | None:
    """User message: the document content block BEFORE the text prompt.
    Returns None when the file type isn't one we can send to the model."""
    block = _document_block(stored_path)
    if block is None:
        return None
    return [
        {
            "role": "user",
            "content": [block, {"type": "text", "text": build_prompt(doc_hint)}],
        }
    ]


# --------------------------------------------------------- the extractor impl

class AnthropicExtractor:
    """Anthropic-backed implementation of the layer-2 ``Extractor`` protocol.

    A ``client`` may be injected for tests; production constructs a real
    ``anthropic.Anthropic()`` which reads ANTHROPIC_API_KEY from the env.
    """

    name = "anthropic:claude-opus-4-8"

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def extract(self, stored_path: str, doc_hint: str) -> dict | None:
        """Extract structured fields, or None on any failure (never raises)."""
        try:
            messages = build_messages(stored_path, doc_hint)
            if messages is None:
                return None
            response = self._client.messages.parse(
                model=MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                messages=messages,
                output_format=ExtractedDoc,
            )
            parsed = response.parsed_output
            if parsed is None:
                return None
            return to_plain_dict(parsed)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, ValidationError):
            return None
        except Exception:  # defensive: null over guess — nothing escapes extract()
            return None
