"""Post-extraction validators. Deterministic normalization first (trim,
abbrev → full state name, MALE → M); anything still invalid is nulled and
recorded as a FieldWarning. The models never mutate — new copies are returned.
"""
from datetime import datetime

from app.schemas import FieldWarning, G28Data, PassportData

# Domain data: 50 states + District of Columbia. Defined once, used everywhere.
STATE_BY_ABBREV: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
US_STATES: frozenset[str] = frozenset(STATE_BY_ABBREV.values())
_STATE_BY_CASEFOLD: dict[str, str] = {name.casefold(): name for name in US_STATES}

_SEX_ALIASES: dict[str, str] = {
    "M": "M", "F": "F", "X": "X",
    "MALE": "M", "FEMALE": "F",
}
VALID_SEX: frozenset[str] = frozenset({"M", "F", "X"})

_DATE_FORMAT = "%Y-%m-%d"


def check_date(value: str | None, field: str) -> tuple[str | None, FieldWarning | None]:
    """Strict YYYY-MM-DD. Trims whitespace; re-emits in canonical zero-padded form."""
    if value is None:
        return None, None
    cleaned = value.strip()
    if not cleaned:
        return None, None
    try:
        parsed = datetime.strptime(cleaned, _DATE_FORMAT)
    except ValueError:
        return None, FieldWarning(
            field=field,
            message=f"Value {cleaned!r} is not a valid YYYY-MM-DD date; field cleared.",
        )
    return parsed.strftime(_DATE_FORMAT), None


def check_sex(value: str | None, field: str) -> tuple[str | None, FieldWarning | None]:
    """Normalize to M/F/X ('MALE' → 'M'); anything else is nulled with a warning."""
    if value is None:
        return None, None
    cleaned = value.strip().upper()
    if not cleaned:
        return None, None
    normalized = _SEX_ALIASES.get(cleaned)
    if normalized is None:
        return None, FieldWarning(
            field=field,
            message=f"Value {value.strip()!r} is not one of M/F/X; field cleared.",
        )
    return normalized, None


def check_state(value: str | None, field: str) -> tuple[str | None, FieldWarning | None]:
    """Normalize to a full US state name ('CA' → 'California', case-insensitive
    full-name match); anything unrecognized is nulled with a warning."""
    if value is None:
        return None, None
    cleaned = value.strip()
    if not cleaned:
        return None, None
    if cleaned in US_STATES:
        return cleaned, None
    by_abbrev = STATE_BY_ABBREV.get(cleaned.upper().replace(".", ""))
    if by_abbrev is not None:
        return by_abbrev, None
    by_name = _STATE_BY_CASEFOLD.get(cleaned.casefold())
    if by_name is not None:
        return by_name, None
    return None, FieldWarning(
        field=field,
        message=f"Value {cleaned!r} is not a US state or the District of Columbia; field cleared.",
    )


def validate_passport(data: PassportData) -> tuple[PassportData, list[FieldWarning]]:
    """Return a new, validated PassportData plus warnings for any nulled field."""
    warnings: list[FieldWarning] = []
    updates: dict[str, str | None] = {}

    for field in ("date_of_birth", "date_of_issue", "date_of_expiration"):
        value, warning = check_date(getattr(data, field), field)
        updates[field] = value
        if warning:
            warnings.append(warning)

    sex, warning = check_sex(data.sex, "sex")
    updates["sex"] = sex
    if warning:
        warnings.append(warning)

    return data.model_copy(update=updates), warnings


def validate_g28(data: G28Data) -> tuple[G28Data, list[FieldWarning]]:
    """Return a new, validated G28Data plus warnings for any nulled field."""
    warnings: list[FieldWarning] = []

    state, state_warning = check_state(data.attorney.state, "attorney.state")
    if state_warning:
        warnings.append(state_warning)
    attorney = data.attorney.model_copy(update={"state": state})

    accreditation_date, date_warning = check_date(
        data.eligibility.accreditation_date, "eligibility.accreditation_date"
    )
    if date_warning:
        warnings.append(date_warning)
    eligibility = data.eligibility.model_copy(update={"accreditation_date": accreditation_date})

    return data.model_copy(update={"attorney": attorney, "eligibility": eligibility}), warnings
