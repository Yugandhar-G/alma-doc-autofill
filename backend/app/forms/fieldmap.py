"""PDF field-map contracts — the allow-list for native form fill.

Mirrors population/field_map.py's discipline for the PDF plane: the specs in
a PdfFieldMap are the ONLY field names the fill engine may touch. Signature,
signature-date, Part 4/5 consent, and barcode fields are structurally
rejected at map construction — they cannot be added, not merely "shouldn't".
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, Literal

PdfAction = Literal["text", "date", "checkbox", "combo_state"]

# Case-insensitive substrings that may never appear in a mapped field name.
FORBIDDEN_FIELD_PATTERNS = (
    "signature", "barcode", "pt4line", "pt5line", "p5_", "dateofsignature",
)


@dataclass(frozen=True)
class PdfFieldSpec:
    """One PDF form field the engine may fill.

    check_when: for checkboxes, the source value that means "check this box".
    The engine never unchecks and never touches the box otherwise (the
    discipline-pair / unit-type traps: exactly one box per group gets checked,
    its siblings are never interacted with).
    """

    field: str   # exact fully-qualified PDF field name
    source: str  # dotted path into the sources dict (e.g. "g28.attorney.city")
    action: PdfAction = "text"
    check_when: Any = True


class PdfFieldMap:
    def __init__(self, form_id: str, specs: tuple[PdfFieldSpec, ...]):
        seen: set[str] = set()
        for spec in specs:
            lowered = spec.field.lower()
            for pattern in FORBIDDEN_FIELD_PATTERNS:
                if pattern in lowered:
                    raise ValueError(
                        f"{form_id}: field {spec.field!r} matches forbidden "
                        f"pattern {pattern!r} — signature/consent/barcode "
                        "fields are structurally unmappable"
                    )
            key = (spec.field, str(spec.check_when))
            if spec.action != "checkbox" and spec.field in seen:
                raise ValueError(f"{form_id}: duplicate mapping for {spec.field!r}")
            seen.add(spec.field)
        self.form_id = form_id
        self.specs = specs

    def __iter__(self) -> Iterator[PdfFieldSpec]:
        return iter(self.specs)


US_STATE_CODES: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "American Samoa": "AS", "Guam": "GU", "Northern Mariana Islands": "MP",
    "Puerto Rico": "PR", "U.S. Virgin Islands": "VI",
}


def state_to_code(value: str) -> str:
    """Full state name (the extraction contract's normal form) → USPS code
    (the PDF combobox's option values). Unknown names raise loudly."""
    if value in US_STATE_CODES:
        return US_STATE_CODES[value]
    if value.upper() in US_STATE_CODES.values():
        return value.upper()  # already a code (edited value passed re-validation)
    raise ValueError(f"unknown US state {value!r}")


def iso_to_uscis_date(value: str) -> str:
    """Extraction normalizes dates to YYYY-MM-DD; paper USCIS forms want
    MM/DD/YYYY. Non-ISO input is a contract violation and raises."""
    return datetime.strptime(value, "%Y-%m-%d").strftime("%m/%d/%Y")
