"""Load and query the checked-in visa→forms registry.

The JSON lives next to this module (it is reference data, not runtime
state); validation happens on every load so a hand-edit that breaks the
contract fails loudly at import-of-use, not at fill time.
"""
import json
from functools import lru_cache
from pathlib import Path

from app.forms.schemas import FormsRegistry

_DATA_PATH = Path(__file__).parent / "data" / "forms_registry.json"


@lru_cache(maxsize=1)
def load_registry() -> FormsRegistry:
    """Parse + validate the registry. Raises on missing or invalid data —
    a broken registry must never silently narrow a filing's checklist."""
    if not _DATA_PATH.exists():
        raise FileNotFoundError(
            f"forms registry missing at {_DATA_PATH}; "
            "run the research synthesis before using the forms package"
        )
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return FormsRegistry.model_validate(raw)
