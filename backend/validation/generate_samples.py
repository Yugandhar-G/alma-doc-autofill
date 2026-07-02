"""Generate G-28 validation samples by editing the example fixture.

The fixture is a flat (non-AcroForm) PDF, so each varied value is replaced
positionally: find the original value's text rect (region-filtered where the
string is ambiguous, e.g. "CA" and "N/A"), redact it, and stamp the new value
at the same baseline in the same font. Every replacement asserts exactly one
matching rect — a layout change fails loudly rather than editing the wrong
span.

Usage: .venv/bin/python -m validation.generate_samples
Output: validation/generated/<persona>.pdf (gitignored)
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz

from validation.personas import PERSONAS

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "Example_G-28.pdf"
OUT_DIR = Path(__file__).parent / "generated"

# Full-Unicode font: base-14 Helvetica is Latin-1 only and silently corrupts
# e.g. Vietnamese ễ into '·' (caught by the first validation run, sample 06).
_FONT_FILE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
_FONT_NAME = "ArialUnicode"
_FONT_SIZE = 10.0
_BASELINE_LIFT = 1.5  # insert_text origin sits on the baseline, not the box bottom


@dataclass(frozen=True)
class FieldSpec:
    page: int
    original: str
    # (x0, y0, x1, y1) the rect's top-left must fall inside; None = unambiguous
    region: tuple[float, float, float, float] | None = None


# Positions verified against the fixture (see docs/agent-usage-log.md).
FIELD_SPECS: dict[str, FieldSpec] = {
    "family": FieldSpec(0, "Smith"),
    "given": FieldSpec(0, "Barbara"),
    "street": FieldSpec(0, "545 Bryant Street"),
    "city": FieldSpec(0, "Palo Alto"),
    "state": FieldSpec(0, "CA", region=(60, 370, 120, 395)),
    "zip": FieldSpec(0, "94301"),
    "country": FieldSpec(0, "United States of America"),
    "mobile": FieldSpec(0, "N/A", region=(50, 570, 100, 595)),
    "email": FieldSpec(0, "immigration@tryalma.ai"),
    "licensing": FieldSpec(0, "State Bar of California"),
    "bar": FieldSpec(0, "12083456"),
    "law_firm": FieldSpec(0, "Alma Legal Services PC"),
    "beneficiary_family": FieldSpec(1, "Jonas"),
    "beneficiary_given": FieldSpec(1, "Joe"),
}


def _find_rect(page: fitz.Page, spec: FieldSpec) -> fitz.Rect:
    rects = page.search_for(spec.original)
    if spec.region is not None:
        x0, y0, x1, y1 = spec.region
        rects = [r for r in rects if x0 <= r.x0 <= x1 and y0 <= r.y0 <= y1]
    if len(rects) != 1:
        raise RuntimeError(
            f"expected exactly 1 rect for {spec.original!r} "
            f"(page {spec.page + 1}, region {spec.region}), found {len(rects)} — "
            "fixture layout changed; re-verify FIELD_SPECS."
        )
    return rects[0]


def generate_sample(persona: dict[str, tuple[str, object]], out_path: Path) -> None:
    doc = fitz.open(FIXTURE)
    # Collect all edits per page first: redactions must be applied before any
    # text insertion, and applying them wipes annotations added afterwards.
    edits: dict[int, list[tuple[fitz.Rect, str]]] = {}
    for key, (printed, _expected) in persona.items():
        spec = FIELD_SPECS[key]
        rect = _find_rect(doc[spec.page], spec)
        edits.setdefault(spec.page, []).append((rect, printed))

    for page_number, page_edits in edits.items():
        page = doc[page_number]
        for rect, _printed in page_edits:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        for rect, printed in page_edits:
            page.insert_text(
                (rect.x0, rect.y1 - _BASELINE_LIFT),
                printed,
                fontname=_FONT_NAME,
                fontfile=_FONT_FILE,
                fontsize=_FONT_SIZE,
                color=(0, 0, 0),
            )
    doc.save(out_path, deflate=True)
    doc.close()


def main() -> int:
    if not FIXTURE.exists():
        print(f"fixture missing: {FIXTURE}", file=sys.stderr)
        return 1
    if not Path(_FONT_FILE).exists():
        print(f"Unicode font missing: {_FONT_FILE}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(exist_ok=True)
    for name, persona in PERSONAS.items():
        out = OUT_DIR / f"{name}.pdf"
        generate_sample(persona, out)
        print(f"generated {out.name} ({len(persona)} fields varied)")
    print(f"\n{len(PERSONAS)} samples in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
