"""Native PDF fill engine — fills official USCIS forms in-process.

No browser anywhere: the library PDF's AcroForm widgets are filled directly
(PyMuPDF), the hybrid XFA layer is stripped from the OUTPUT copy so every
viewer renders the filled AcroForm (the pristine library file is never
modified), and the result is verified by re-opening the output and reading
every mapped field back (fill-then-diff, same discipline as the HTML
population report).

Rules carried over from the population plane:
- Field names come ONLY from app/forms/maps (allow-list; signature/consent/
  barcode fields structurally rejected there).
- Nulls are skipped, never written.
- Checkboxes: exactly one box per group is checked; siblings never touched.
"""
import logging
from pathlib import Path
from typing import Any, Literal, Optional

import fitz  # PyMuPDF

from app.forms.fieldmap import PdfFieldMap, iso_to_uscis_date, state_to_code
from app.forms.library import LIBRARY_DIR
from app.forms.maps import PDF_FIELD_MAPS
from app.population.fill import resolve_source
from pydantic import BaseModel

logger = logging.getLogger("yunaki.forms.fill")


class PdfFieldResult(BaseModel):
    field: str
    source: str
    status: Literal["filled", "skipped_null", "mismatch", "error"]
    expected: Optional[str] = None
    actual: Optional[str] = None
    detail: Optional[str] = None


class PdfFillReport(BaseModel):
    form_id: str
    library_file: str
    output_file: str
    xfa_stripped: bool
    results: list[PdfFieldResult]

    @property
    def verified(self) -> bool:
        return all(r.status in ("filled", "skipped_null") for r in self.results)


def library_pdf_path(form_id: str) -> Path:
    """Locate the stored library PDF for a form id; loud when absent."""
    matches = sorted(LIBRARY_DIR.glob(f"{form_id}__*.pdf"))
    if not matches:
        raise FileNotFoundError(
            f"no library PDF for {form_id!r} in {LIBRARY_DIR}; "
            "run `python -m app.forms.library` first"
        )
    return matches[-1]


def _prepare_value(spec: Any, raw: Any) -> tuple[str | bool | None, str | None]:
    """Resolve the wire value for a spec. Returns (value, error). A None
    value with no error means 'skip'."""
    if spec.action == "checkbox":
        return (True, None) if raw == spec.check_when else (None, None)
    text = str(raw)
    try:
        if spec.action == "date":
            return iso_to_uscis_date(text), None
        if spec.action == "combo_state":
            return state_to_code(text), None
    except ValueError as exc:
        return None, str(exc)
    return text, None


def _strip_xfa(doc: fitz.Document) -> bool:
    """Remove the XFA layer so viewers render the filled AcroForm. Returns
    whether an XFA entry was found and nulled."""
    catalog = doc.pdf_catalog()
    acro_type, acro_val = doc.xref_get_key(catalog, "AcroForm")
    if acro_type == "xref":
        acro_xref = int(acro_val.split()[0])
        if doc.xref_get_key(acro_xref, "XFA")[0] != "null":
            doc.xref_set_key(acro_xref, "XFA", "null")
            return True
        return False
    if doc.xref_get_key(catalog, "AcroForm/XFA")[0] != "null":
        doc.xref_set_key(catalog, "AcroForm/XFA", "null")
        return True
    return False


def fill_pdf(form_id: str, sources: dict[str, Any], output_path: Path) -> PdfFillReport:
    """Fill the library PDF for `form_id` from `sources` (the same dict shape
    the HTML population engine consumes), write the filled copy to
    `output_path`, and verify by read-back. Never mutates the library file."""
    field_map: PdfFieldMap | None = PDF_FIELD_MAPS.get(form_id)
    if field_map is None:
        raise KeyError(f"no PDF field map registered for {form_id!r}")
    library_file = library_pdf_path(form_id)

    plan: list[tuple[Any, str | bool | None]] = []
    results: list[PdfFieldResult] = []
    for spec in field_map:
        raw = resolve_source(sources, spec.source)
        if raw is None:
            results.append(PdfFieldResult(
                field=spec.field, source=spec.source, status="skipped_null"))
            continue
        value, error = _prepare_value(spec, raw)
        if error is not None:
            results.append(PdfFieldResult(
                field=spec.field, source=spec.source, status="error", detail=error))
            continue
        if value is None:  # checkbox whose condition didn't match: never touched
            results.append(PdfFieldResult(
                field=spec.field, source=spec.source, status="skipped_null",
                detail="checkbox condition not met; untouched"))
            continue
        plan.append((spec, value))

    doc = fitz.open(library_file)
    # Widget handles are only valid while their page is current — fill inline
    # during a single page sweep, never from a cross-page collection.
    pending: dict[str, tuple[Any, str | bool]] = {
        spec.field: (spec, value) for spec, value in plan
    }
    expected: dict[str, tuple[Any, str | bool]] = {}
    for page in doc:
        for widget in page.widgets() or []:
            entry = pending.pop(widget.field_name, None)
            if entry is None:
                continue
            spec, value = entry
            widget.field_value = value
            widget.update()
            expected[widget.field_name] = (spec, value)
    for field, (spec, _value) in pending.items():
        results.append(PdfFieldResult(
            field=field, source=spec.source, status="error",
            detail="field not present in PDF (edition drift?)"))

    xfa_stripped = _strip_xfa(doc)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()

    # Read-back verification against the saved artifact.
    check = fitz.open(str(output_path))
    actual = {
        w.field_name: w.field_value
        for page in check for w in (page.widgets() or [])
    }
    check.close()
    for field, (spec, value) in expected.items():
        got = actual.get(field)
        if spec.action == "checkbox":
            ok = got not in (None, "", "Off", False)
        else:
            ok = got == value
        results.append(PdfFieldResult(
            field=field, source=spec.source,
            status="filled" if ok else "mismatch",
            expected=str(value), actual=None if got is None else str(got)))

    report = PdfFillReport(
        form_id=form_id,
        library_file=library_file.name,
        output_file=str(output_path),
        xfa_stripped=xfa_stripped,
        results=results,
    )
    filled = sum(1 for r in results if r.status == "filled")
    logger.info(
        "filled %s: %d filled, %d skipped, verified=%s",
        form_id, filled,
        sum(1 for r in results if r.status == "skipped_null"),
        report.verified,
    )
    return report
