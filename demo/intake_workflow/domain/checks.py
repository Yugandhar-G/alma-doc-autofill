"""Layer-1 deterministic checks (private helper for app.domain.api).

Two entry points, both return an ``AutoCheckResult`` and neither ever raises
on hostile input — an unreadable/unexpected file or a broken validation rule
produces a flagged ``could_not_verify`` finding (null over guess), never an
exception and never a silent pass.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from intake_workflow.schemas import (
    AutoCheckFinding,
    AutoCheckResult,
    CheckStatus,
    ChecklistItem,
    QuestionField,
    utcnow,
)

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
MIN_BYTES = 20 * 1024            # 20 KB: below this a scan is likely blurry/incomplete
MAX_BYTES = 25 * 1024 * 1024     # 25 MB
MIN_IMAGE_PX = 600
MAX_PDF_PAGES = 100


def _result(findings: list[AutoCheckFinding], now) -> AutoCheckResult:
    status = CheckStatus.flagged if findings else CheckStatus.passed
    return AutoCheckResult(
        layer=1, status=status, findings=findings, checked_at=now or utcnow()
    )


# --------------------------------------------------------------------- documents

def check_file(stored_path: str, item: ChecklistItem, now=None) -> AutoCheckResult:
    """Deterministic layer-1 file checks. Never raises."""
    findings: list[AutoCheckFinding] = []
    try:
        ext = Path(stored_path).suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXTENSIONS:
            findings.append(
                AutoCheckFinding(
                    code="bad_extension",
                    message="This file type isn't one we can accept. "
                    "Please upload a PDF, JPG, or PNG.",
                )
            )

        size = None
        try:
            size = os.path.getsize(stored_path)
        except OSError:
            findings.append(
                AutoCheckFinding(
                    code="could_not_verify",
                    message="We couldn't open this file to check it. "
                    "A member of our team will take a look.",
                )
            )
        if size is not None:
            if size < MIN_BYTES:
                findings.append(
                    AutoCheckFinding(
                        code="too_small",
                        message="This file is very small, so the scan may be blurry "
                        "or incomplete. Please re-upload a clear, full copy.",
                    )
                )
            elif size > MAX_BYTES:
                findings.append(
                    AutoCheckFinding(
                        code="too_large",
                        message="This file is larger than 25 MB. Please upload a "
                        "smaller, clear scan.",
                    )
                )

        if ext == "pdf":
            findings.extend(_check_pdf(stored_path))
        elif ext in {"jpg", "jpeg", "png"}:
            findings.extend(_check_image(stored_path))
    except Exception:  # pragma: no cover - defensive: never raise on hostile input
        findings.append(
            AutoCheckFinding(
                code="could_not_verify",
                message="We couldn't automatically verify this file. "
                "A member of our team will take a look.",
            )
        )
    return _result(findings, now)


def _check_pdf(stored_path: str) -> list[AutoCheckFinding]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(stored_path)
        pages = len(reader.pages)
    except Exception:
        return [
            AutoCheckFinding(
                code="unreadable_pdf",
                message="We couldn't open this PDF. Please re-save or re-scan it "
                "and upload again.",
            )
        ]
    if pages < 1 or pages > MAX_PDF_PAGES:
        return [
            AutoCheckFinding(
                code="page_count",
                message="This PDF's page count looks off. Please upload the "
                "complete document as a single, reasonable-length file.",
            )
        ]
    return []


def _check_image(stored_path: str) -> list[AutoCheckFinding]:
    try:
        from PIL import Image

        with Image.open(stored_path) as probe:
            probe.verify()  # catches truncated / corrupt image data
        with Image.open(stored_path) as im:
            width, height = im.size
    except Exception:
        return [
            AutoCheckFinding(
                code="could_not_verify",
                message="We couldn't open this image. Please upload a clear "
                "PDF, JPG, or PNG.",
            )
        ]
    if width < MIN_IMAGE_PX or height < MIN_IMAGE_PX:
        return [
            AutoCheckFinding(
                code="low_resolution",
                message="This image is a little low-resolution. Please upload a "
                "sharper photo or scan (at least 600x600 pixels).",
            )
        ]
    return []


# ----------------------------------------------------------------- questionnaires

def _format_message(field: QuestionField) -> str:
    if field.hint:
        return f"{field.label} doesn't look right - {field.hint}"
    return f"{field.label} doesn't look right. Please double-check the format."


def check_answers(item: ChecklistItem, answers: dict[str, str], now=None) -> AutoCheckResult:
    """Deterministic layer-1 questionnaire checks: required present + non-blank,
    pattern match, ISO-parseable dates. Never raises."""
    from datetime import date as _date

    findings: list[AutoCheckFinding] = []
    for field in item.fields:
        value = (answers.get(field.key) or "").strip()
        if not value:
            if field.required:
                findings.append(
                    AutoCheckFinding(
                        code="missing_field",
                        message=f"Please answer: {field.label}.",
                    )
                )
            continue

        if field.pattern:
            try:
                if re.fullmatch(field.pattern, value) is None:
                    findings.append(
                        AutoCheckFinding(
                            code="invalid_format", message=_format_message(field)
                        )
                    )
            except re.error:
                findings.append(
                    AutoCheckFinding(
                        code="could_not_verify",
                        message=f"We couldn't validate {field.label}. "
                        "A member of our team will take a look.",
                    )
                )

        if field.type == "date":
            try:
                _date.fromisoformat(value)
            except ValueError:
                findings.append(
                    AutoCheckFinding(
                        code="invalid_date",
                        message=f"{field.label} needs to be a valid date "
                        "in YYYY-MM-DD format.",
                    )
                )

    return _result(findings, now)
