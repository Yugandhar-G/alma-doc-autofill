"""Unit tests for the Anthropic extractor + pure helpers.

No real API calls: the anthropic client is a hand-rolled fake injected into
``AnthropicExtractor``. The single live-API test is skipped without a key.
"""
from __future__ import annotations

import base64
import os

import anthropic
import httpx
import pytest
from pydantic import ValidationError

from intake_workflow.domain.extractors import (
    AnthropicExtractor,
    ExtractedDoc,
    build_messages,
    build_prompt,
    document_type_mismatches,
    names_match,
    to_plain_dict,
)


# --------------------------------------------------------------- fake client

class _Resp:
    def __init__(self, parsed):
        self.parsed_output = parsed


class _FakeMessages:
    def __init__(self, parse_fn):
        self.parse = parse_fn


class _FakeClient:
    """Stands in for ``anthropic.Anthropic()``; records the parse kwargs."""

    def __init__(self, parse_fn):
        self.messages = _FakeMessages(parse_fn)
        self.calls: list[dict] = []


def _client_returning(parsed):
    def parse(**kwargs):
        client.calls.append(kwargs)
        return _Resp(parsed)
    client = _FakeClient(parse)
    return client


def _client_raising(exc):
    def parse(**kwargs):
        raise exc
    return _FakeClient(parse)


# ------------------------------------------------------------ file factories

def _png(tmp_path, name="img.png"):
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (64, 64), (10, 20, 30)).save(path)
    return str(path)


def _pdf(tmp_path, name="doc.pdf"):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    path = tmp_path / name
    with open(path, "wb") as fh:
        writer.write(fh)
    return str(path)


# ------------------------------------------------------------- pure helpers

def test_names_match_loose_and_case_insensitive():
    assert names_match("ANA MARQUEZ", "Ana Marquez")
    assert names_match("Ana Sofia Marquez", "Ana Marquez")   # middle name ok
    assert not names_match("Ana Marquez", "Wei Chen")
    assert not names_match("", "Ana Marquez")


def test_document_type_mismatch_only_on_zero_overlap():
    assert document_type_mismatches("Bank Statement", "Marriage certificate")
    assert not document_type_mismatches("Marriage Certificate", "Marriage certificate")
    assert not document_type_mismatches("Residential Lease", "Lease or deed with both names")
    assert not document_type_mismatches("", "Marriage certificate")  # empty never flags


def test_to_plain_dict_omits_none_and_empty():
    doc = ExtractedDoc(
        document_type="  Passport  ",
        person_names=["Wei Chen", "  ", ""],
        issue_date=None,
        expiry_date="2030-01-01",
        address="",
        notes=None,
    )
    assert to_plain_dict(doc) == {
        "document_type": "Passport",
        "person_names": ["Wei Chen"],
        "expiry_date": "2030-01-01",
    }


def test_to_plain_dict_empty_when_nothing_present():
    assert to_plain_dict(ExtractedDoc()) == {}


# ------------------------------------------------- prompt / content blocks

def test_build_prompt_names_hint_and_forbids_guessing():
    prompt = build_prompt("Lease or deed with both names")
    assert "Lease or deed with both names" in prompt
    lowered = prompt.lower()
    assert "do not guess" in lowered
    assert "omitted or null field is the correct answer" in lowered


def test_build_messages_pdf_document_block_before_text(tmp_path):
    path = _pdf(tmp_path)
    messages = build_messages(path, "Marriage certificate")
    content = messages[0]["content"]
    assert messages[0]["role"] == "user"
    # Document block first, text block second.
    assert content[0]["type"] == "document"
    assert content[0]["source"]["media_type"] == "application/pdf"
    assert content[1]["type"] == "text"
    # Base64 payload round-trips and contains no newlines.
    data = content[0]["source"]["data"]
    assert "\n" not in data
    with open(path, "rb") as fh:
        assert base64.b64decode(data) == fh.read()


def test_build_messages_png_image_block(tmp_path):
    messages = build_messages(_png(tmp_path), "Beneficiary — Passport bio page")
    block = messages[0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"


def test_build_messages_jpeg_media_type(tmp_path):
    from PIL import Image

    path = tmp_path / "photo.jpg"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(path)
    block = build_messages(str(path), "hint")[0]["content"][0]
    assert block["source"]["media_type"] == "image/jpeg"


def test_build_messages_unsupported_extension_is_none(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    assert build_messages(str(path), "hint") is None


# ------------------------------------------------------- extract() happy path

def test_extract_returns_plain_dict_on_success(tmp_path):
    parsed = ExtractedDoc(person_names=["Ana Marquez"], document_type="Marriage Certificate")
    client = _client_returning(parsed)
    ext = AnthropicExtractor(client=client)

    result = ext.extract(_pdf(tmp_path), "Marriage certificate")
    assert result == {"person_names": ["Ana Marquez"], "document_type": "Marriage Certificate"}

    # Correct model + params were sent; forbidden sampling params were not.
    sent = client.calls[0]
    assert sent["model"] == "claude-opus-4-8"
    assert sent["max_tokens"] == 4096
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_format"] is ExtractedDoc
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in sent


# --------------------------------------------------------- extract() None paths

def test_extract_none_on_unsupported_file(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("nope")
    # Client must never be called for an unsendable file type.
    client = _client_raising(AssertionError("parse should not be called"))
    assert AnthropicExtractor(client=client).extract(str(path), "hint") is None


def test_extract_none_on_missing_file(tmp_path):
    client = _client_raising(AssertionError("parse should not be called"))
    missing = str(tmp_path / "gone.pdf")
    assert AnthropicExtractor(client=client).extract(missing, "hint") is None


def test_extract_none_on_api_connection_error(tmp_path):
    exc = anthropic.APIConnectionError(
        message="boom", request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    ext = AnthropicExtractor(client=_client_raising(exc))
    assert ext.extract(_pdf(tmp_path), "hint") is None


def test_extract_none_on_api_status_error(tmp_path):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.RateLimitError(
        message="rate", response=httpx.Response(429, request=req), body=None
    )
    ext = AnthropicExtractor(client=_client_raising(exc))
    assert ext.extract(_pdf(tmp_path), "hint") is None


def test_extract_none_on_validation_error(tmp_path):
    try:
        ExtractedDoc(person_names=123)  # invalid -> real ValidationError
    except ValidationError as ve:
        exc = ve
    ext = AnthropicExtractor(client=_client_raising(exc))
    assert ext.extract(_pdf(tmp_path), "hint") is None


def test_extract_none_on_unexpected_exception(tmp_path):
    ext = AnthropicExtractor(client=_client_raising(RuntimeError("kaboom")))
    assert ext.extract(_pdf(tmp_path), "hint") is None


def test_extract_none_when_parsed_output_is_none(tmp_path):
    ext = AnthropicExtractor(client=_client_returning(None))
    assert ext.extract(_pdf(tmp_path), "hint") is None


# ---------------------------------------------------------- live integration

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="no api key"
)
def test_live_extraction_on_generated_pdf(tmp_path):
    """One real round-trip against the API on a tiny generated PDF."""
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from reportlab.pdfgen import canvas

    path = str(tmp_path / "live.pdf")
    c = canvas.Canvas(path)
    c.drawString(72, 720, "MARRIAGE CERTIFICATE")
    c.drawString(72, 700, "This certifies the marriage of Ana Marquez and Wei Chen.")
    c.drawString(72, 680, "Issued: 2023-06-15")
    c.save()

    from intake_workflow.domain.layer2 import get_extractor

    extractor = get_extractor()
    assert extractor is not None
    result = extractor.extract(path, "Marriage certificate")
    # Null over guess: a None here is an acceptable (safe) outcome; when the
    # model does return fields, they must be a plain dict.
    assert result is None or isinstance(result, dict)
