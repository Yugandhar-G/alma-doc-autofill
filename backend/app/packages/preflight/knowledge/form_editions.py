"""USCIS form-edition registry — sourced from the verified visa→forms registry.

USCIS rejects filings submitted on a superseded form edition, so a stale
edition is a real RFE/rejection driver. But a *wrong* current-edition date is
this package's fabrication defect class: claiming "the current G-28 edition is
05/31/24" when it is not would be worse than saying nothing.

So editions are never hand-typed here. They are derived from
``app.forms.registry.load_registry()`` — the user-authored reference plane whose
loader validates every entry and whose null ``edition_date`` means "not
verifiable at research time" (never a guess). The adapter below:

    - emits ONE FormEdition per unique form_id across all visa profiles,
    - includes a form ONLY when its ``edition_date`` is non-null (nulls are
      skipped silently — an absent edition keeps the check dormant for that
      form, never defaulted),
    - cites that form's official ``form_page_url`` as the edition's source_url,
    - fails loudly if the forms registry is missing/invalid (the loader raises;
      we let it propagate rather than narrow a filing's edition check silently).

Lookup is exact-case against the registry's own form_id spelling (e.g. "G-28").
The packet plane maps its g28 doc_type to "g-28" (lowercase, see packet.py),
which intentionally does not match — v0 extraction cannot read an edition marker
off the target form anyway, so the production check stays dormant for real
uploads and fires only for a synthetic edition declared against a registry-cased
form_id.

Test seam: ``_REGISTRY`` is an override map, empty in production. Tests patch it
(``patch.object(form_editions, "_REGISTRY", {...})``) to inject synthetic
editions; an override entry shadows the derived registry for that form_id.
"""
from dataclasses import dataclass
from functools import lru_cache

from app.forms.registry import load_registry


@dataclass(frozen=True)
class FormEdition:
    form_id: str
    current_edition: str  # exact edition string USCIS prints, e.g. "05/31/24"
    source_url: str  # authoritative page the edition was transcribed from


# OVERRIDE SEAM — empty in production. Tests inject synthetic editions here; an
# entry present here shadows the derived registry for that exact form_id.
_REGISTRY: dict[str, FormEdition] = {}


@lru_cache(maxsize=1)
def _derived_registry() -> dict[str, FormEdition]:
    """Build the edition map from the verified visa→forms registry.

    One entry per unique form_id whose edition_date is non-null; the first
    non-null occurrence wins (the reference plane already guarantees a form_id
    never carries two different editions). Raises via ``load_registry`` if the
    registry is missing or fails validation."""
    registry = load_registry()
    derived: dict[str, FormEdition] = {}
    for profile in registry.visas:
        for form in profile.forms:
            if form.edition_date is None:
                continue  # not verifiable → never defaulted
            key = form.form_id.casefold()
            if key in derived:
                continue  # first non-null wins; editions are consistent
            derived[key] = FormEdition(
                form_id=form.form_id,
                current_edition=form.edition_date,
                source_url=form.form_page_url,
            )
    return derived


def edition_for(form_id: str) -> FormEdition | None:
    """The registered current edition for a form, or None when the form has no
    verified entry. None means the check stays silent for that form.

    Lookup is case-insensitive: the packet plane cases form ids as doc types
    ("g-28") while the reference registry uses official casing ("G-28") — a
    case mismatch must never silently disable an edition check.

    The override seam (``_REGISTRY``) is consulted first so tests can inject
    editions without touching the reference registry; otherwise the derived
    registry answers."""
    override = _REGISTRY.get(form_id) or _REGISTRY.get(form_id.casefold())
    if override is not None:
        return override
    return _derived_registry().get(form_id.casefold())
