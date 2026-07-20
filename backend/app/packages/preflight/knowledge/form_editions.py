"""USCIS form-edition registry — the mechanism, deliberately EMPTY in production.

USCIS rejects filings submitted on a superseded form edition, so a stale
edition is a real RFE/rejection driver. But a *wrong* current-edition date is
the fabrication defect class: claiming "the current G-28 edition is 05/31/24"
when it is not would be worse than saying nothing. So the production registry
below is intentionally EMPTY.

    Entries here must be populated ONLY by a verification pass that reads the
    authoritative USCIS forms page for each form_id and transcribes the exact
    edition date + source URL. Do NOT hand-add entries from memory.

The target form snapshot (tests/data/form_snapshot.html) carries no edition
marker, so there is nothing to seed from the repo either. Tests exercise the
check with a SYNTHETIC registry. With an empty registry the check reports
nothing (silence over noise): see checks.form_edition_currency.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FormEdition:
    form_id: str
    current_edition: str  # exact edition string USCIS prints, e.g. "05/31/24"
    source_url: str  # authoritative page the edition was transcribed from


# PRODUCTION REGISTRY — INTENTIONALLY EMPTY. See module docstring: entries are
# added only by a verification pass, never from memory. Tests inject their own.
_REGISTRY: dict[str, FormEdition] = {}


def edition_for(form_id: str) -> FormEdition | None:
    """The registered current edition for a form, or None when the form has no
    verified entry. None means the check stays silent for that form."""
    return _REGISTRY.get(form_id)
