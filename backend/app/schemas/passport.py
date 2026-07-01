"""Passport extraction schema. Every field Optional, default None —
a missing value is a valid result, never a parsing failure."""
from pydantic import BaseModel, Field


class PassportData(BaseModel):
    surname: str | None = Field(None, description="Family name exactly as printed, incl. diacritics")
    given_names: str | None = Field(None, description="First name(s) exactly as printed")
    middle_names: str | None = Field(None, description="Middle name(s) if the passport separates them")
    passport_number: str | None = None
    country_of_issue: str | None = Field(None, description="Full English country name")
    nationality: str | None = Field(None, description="Full English country/nationality name")
    date_of_birth: str | None = Field(None, description="YYYY-MM-DD")
    place_of_birth: str | None = None
    sex: str | None = Field(None, description="Single letter: M, F, or X")
    date_of_issue: str | None = Field(None, description="YYYY-MM-DD")
    date_of_expiration: str | None = Field(None, description="YYYY-MM-DD")
