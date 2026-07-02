"""G-28 extraction schema. Sections mirror the form's parts.
Every field Optional, default None."""
from typing import Literal

from pydantic import BaseModel, Field


class AttorneyInfo(BaseModel):
    online_account_number: str | None = None
    family_name: str | None = None
    given_name: str | None = None
    middle_name: str | None = None
    street_number_and_name: str | None = None
    apt_ste_flr: Literal["apt", "ste", "flr"] | None = Field(
        None, description="Which unit-type box is marked, if any. 'N/A' → null"
    )
    apt_ste_flr_number: str | None = None
    city: str | None = None
    state: str | None = Field(None, description="Full US state name, e.g. 'California'")
    zip_code: str | None = None
    country: str | None = Field(None, description="Full English country name")
    daytime_phone: str | None = Field(
        None,
        description="Item 4 Daytime Telephone Number only. Blank → null. "
        "Never the fax number — fax is not extracted.",
    )
    mobile_phone: str | None = Field(
        None,
        description="Item 5 Mobile Telephone Number only. Blank or N/A → null. "
        "Never the fax or daytime number.",
    )
    email: str | None = None


class EligibilityInfo(BaseModel):
    is_attorney: bool | None = Field(None, description="Box 1.a checked")
    licensing_authority: str | None = None
    bar_number: str | None = None
    subject_to_discipline: bool | None = Field(
        None, description="1.c — True if 'am' subject to orders, False if 'am not', null if unmarked"
    )
    law_firm: str | None = None
    is_accredited_representative: bool | None = Field(None, description="Box 2.a checked")
    recognized_organization: str | None = None
    accreditation_date: str | None = Field(None, description="YYYY-MM-DD")
    is_associated: bool | None = Field(None, description="Box 3 checked")
    associated_with_name: str | None = None
    is_law_student: bool | None = Field(None, description="Box 4.a checked")
    law_student_name: str | None = None


class BeneficiaryInfo(BaseModel):
    family_name: str | None = None
    given_name: str | None = None
    middle_name: str | None = None


class G28Data(BaseModel):
    attorney: AttorneyInfo = Field(default_factory=AttorneyInfo)
    eligibility: EligibilityInfo = Field(default_factory=EligibilityInfo)
    beneficiary: BeneficiaryInfo = Field(default_factory=BeneficiaryInfo)
