"""Per-form PDF field maps — the only source of fillable field names.

One module per form; register each map here. The registry mirrors
population/field_map.py's role for the PDF plane.
"""
from app.forms.fieldmap import PdfFieldMap
from app.forms.maps.g28 import G28_PDF_MAP

PDF_FIELD_MAPS: dict[str, PdfFieldMap] = {
    "G-28": G28_PDF_MAP,
}
