"""Pydantic contracts for the visa→forms registry.

The registry JSON is the source of truth; these schemas are its gate. Every
form entry cites the official form page it was verified against. A null
edition_date or pdf_url means "not verifiable at research time" — never a
guess (extraction contract applied to reference data).
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

FormRole = Literal[
    "primary_petition",  # the form that IS the filing
    "supplement",        # part of the primary form's package (I-129 supplements, I-130A)
    "companion",         # filed alongside (I-765/I-131 with I-485)
    "prerequisite",      # must exist first (LCA, PERM)
    "beneficiary",       # completed by/about the beneficiary
    "attorney_rep",      # G-28 family
    "optional",          # premium processing, e-notification, dependents
]

IssuingAgency = Literal["USCIS", "DOL", "DOS"]

_ALLOWED_PDF_HOSTS = ("www.uscis.gov", "uscis.gov")
_ALLOWED_PAGE_HOSTS = _ALLOWED_PDF_HOSTS + (
    "www.dol.gov", "dol.gov", "flag.dol.gov",
    "travel.state.gov", "eforms.state.gov", "ceac.state.gov",
    "www.foreignlaborcert.doleta.gov",
)


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


class FormRef(BaseModel):
    """One form a visa classification uses, verified against its official page."""

    form_id: str = Field(min_length=2, max_length=20)
    title: str = Field(min_length=3)
    role: FormRole
    edition_date: Optional[str] = None
    form_page_url: str
    pdf_url: Optional[str] = None
    issuing_agency: IssuingAgency = "USCIS"
    notes: Optional[str] = None

    @field_validator("form_page_url")
    @classmethod
    def _page_official(cls, v: str) -> str:
        if not v.startswith("https://") or _host_of(v) not in _ALLOWED_PAGE_HOSTS:
            raise ValueError(f"form_page_url must be an official agency page: {v}")
        return v

    @field_validator("pdf_url")
    @classmethod
    def _pdf_official(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not v.startswith("https://") or _host_of(v) not in _ALLOWED_PDF_HOSTS:
            raise ValueError(f"pdf_url must be an official uscis.gov URL: {v}")
        return v


class SupportingDocument(BaseModel):
    """A non-form document the filing needs (certificates, letters, evidence)."""

    name: str = Field(min_length=3)
    required: bool = True
    notes: Optional[str] = None
    source_url: Optional[str] = None


class VisaProfile(BaseModel):
    """One visa classification: its forms and supporting-document checklist."""

    visa_code: str = Field(min_length=2, max_length=32)
    category: Literal[
        "nonimmigrant_employment", "immigrant_employment", "family",
        "adjustment", "consular", "citizenship", "cross_cutting",
    ]
    description: str
    forms: list[FormRef]
    supporting_documents: list[SupportingDocument] = []

    @field_validator("forms")
    @classmethod
    def _unique_roles_ids(cls, v: list[FormRef]) -> list[FormRef]:
        seen: set[tuple[str, str]] = set()
        for f in v:
            key = (f.form_id, f.role)
            if key in seen:
                raise ValueError(f"duplicate form entry {key}")
            seen.add(key)
        return v


class FormsRegistry(BaseModel):
    """The full registry: every visa profile plus research provenance."""

    version: str
    researched_on: str  # YYYY-MM-DD; editions drift, staleness must be visible
    visas: list[VisaProfile]
    sources: list[str] = []

    @field_validator("visas")
    @classmethod
    def _unique_visa_codes(cls, v: list[VisaProfile]) -> list[VisaProfile]:
        codes = [p.visa_code for p in v]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate visa_code in registry")
        return v

    def profile(self, visa_code: str) -> VisaProfile:
        for p in self.visas:
            if p.visa_code == visa_code:
                return p
        raise KeyError(f"unknown visa_code {visa_code!r}")

    def unique_pdf_forms(self) -> list[FormRef]:
        """Deduplicated downloadable forms across all visas (by form_id),
        preferring entries that carry an edition_date."""
        best: dict[str, FormRef] = {}
        for profile in self.visas:
            for form in profile.forms:
                if form.pdf_url is None:
                    continue
                current = best.get(form.form_id)
                if current is None or (
                    current.edition_date is None and form.edition_date is not None
                ):
                    best[form.form_id] = form
        return sorted(best.values(), key=lambda f: f.form_id)
