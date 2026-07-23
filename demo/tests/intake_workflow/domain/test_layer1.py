"""Layer-1 deterministic file checks — never raises, null over guess."""
from __future__ import annotations

import os

from intake_workflow.domain import api
from intake_workflow.schemas import CheckStatus, ChecklistItem, PartyRole


def _item() -> ChecklistItem:
    return ChecklistItem(key="marriage_cert", label="Marriage certificate",
                         assignee=PartyRole.petitioner)


def _codes(result):
    return [f.code for f in result.findings]


def test_bad_extension(tmp_path, now):
    path = tmp_path / "scan.txt"
    path.write_bytes(b"x" * (30 * 1024))
    result = api.layer1_check_file(str(path), _item(), now)
    assert result.status == CheckStatus.flagged
    assert "bad_extension" in _codes(result)


def test_too_small(make_pdf, now):
    path = make_pdf("tiny.pdf", pad_bytes=0)
    assert os.path.getsize(path) < 20 * 1024
    result = api.layer1_check_file(path, _item(), now)
    assert result.status == CheckStatus.flagged
    assert "too_small" in _codes(result)


def test_unreadable_pdf(tmp_path, now):
    path = tmp_path / "broken.pdf"
    # A .pdf extension over the size floor whose bytes are not a real PDF.
    path.write_bytes(b"this is definitely not a pdf file " * 1000)
    result = api.layer1_check_file(str(path), _item(), now)
    assert result.status == CheckStatus.flagged
    assert "unreadable_pdf" in _codes(result)
    assert "too_small" not in _codes(result)  # padded past the size floor


def test_valid_pdf(make_pdf, now):
    path = make_pdf("good.pdf")
    result = api.layer1_check_file(path, _item(), now)
    assert result.status == CheckStatus.passed
    assert result.findings == []


def test_missing_file_never_raises(tmp_path, now):
    result = api.layer1_check_file(str(tmp_path / "nope.pdf"), _item(), now)
    assert result.status == CheckStatus.flagged
    assert "could_not_verify" in _codes(result)


def test_low_resolution_image(tmp_path, now):
    from PIL import Image

    path = tmp_path / "small.png"
    Image.new("RGB", (300, 300), (120, 40, 60)).save(path)
    result = api.layer1_check_file(str(path), _item(), now)
    assert result.status == CheckStatus.flagged
    assert "low_resolution" in _codes(result)


def test_valid_image(tmp_path, now):
    from PIL import Image

    path = tmp_path / "big.png"
    # Noise doesn't compress, so a 700x700 PNG clears both the size and px floors.
    Image.effect_noise((700, 700), 100).convert("RGB").save(path)
    assert os.path.getsize(path) >= 20 * 1024
    result = api.layer1_check_file(str(path), _item(), now)
    assert result.status == CheckStatus.passed
    assert result.findings == []
