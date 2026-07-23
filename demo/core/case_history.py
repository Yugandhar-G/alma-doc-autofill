"""Case-history contract + SQLite store — Jul 23 scope change (pending Nanda ack).

The shared /core contract for case history: pydantic models mirroring the firm's
two eImmigration questionnaires (petitioner + beneficiary) 1:1, plus a store that
keeps exactly ONE current record per (case_id, role). Updates overwrite; the event
bus (`case_history.updated`) is the audit trail.

Store style mirrors drafts.py: guarded writes, fail loud, model_copy over mutation,
and PII-FREE event payloads (workplan §4.4 — never names/emails/values on the bus).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .events import emit
from .models import PartyRole, Event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Shared sub-models. Every scalar is `str | None = None`, every list defaults
# to empty, every nested model is `<Model> | None = None` — a null is correct,
# a plausible guess is a defect (extraction contract, applied to intake data).
# --------------------------------------------------------------------------- #

class PersonName(BaseModel):
    first: str | None = None
    middle: str | None = None
    last: str | None = None


class PhoneNumbers(BaseModel):
    mobile: str | None = None
    daytime: str | None = None
    evening: str | None = None
    work: str | None = None


class AddressEntry(BaseModel):
    street: str | None = None
    unit_type: str | None = None
    unit_number: str | None = None
    city: str | None = None
    county: str | None = None
    state_province: str | None = None
    zip_postal: str | None = None
    country: str | None = None
    from_date: str | None = None
    to_date: str | None = None


class MarriageEntry(BaseModel):
    marriage_date: str | None = None
    marriage_city: str | None = None
    marriage_state: str | None = None
    marriage_country: str | None = None
    termination_date: str | None = None
    termination_city: str | None = None
    termination_state: str | None = None
    termination_country: str | None = None
    current: bool | None = None
    spouse_name: PersonName | None = None
    spouse_maiden_name: str | None = None
    spouse_birth_date: str | None = None
    spouse_sex: str | None = None


class SpouseInfo(BaseModel):
    name: PersonName | None = None
    maiden_name: str | None = None
    sex: str | None = None
    birth_date: str | None = None
    birth_city: str | None = None
    birth_country: str | None = None


class EmploymentEntry(BaseModel):
    employer_name: str | None = None
    job_title: str | None = None
    job_description: str | None = None
    hours_per_week: str | None = None
    email: str | None = None
    phone: str | None = None
    fax: str | None = None
    address: AddressEntry | None = None
    from_date: str | None = None
    to_date: str | None = None
    current: bool | None = None


class ParentInfo(BaseModel):
    name: PersonName | None = None
    maiden_name: str | None = None
    other_names: str | None = None
    marital_status: str | None = None
    sex: str | None = None
    birth_date: str | None = None
    birth_city: str | None = None
    birth_state: str | None = None
    birth_country: str | None = None
    current_city_of_residence: str | None = None
    current_country_of_residence: str | None = None
    nationality: str | None = None
    alien_number: str | None = None


class ChildInfo(BaseModel):
    relationship: str | None = None
    name: PersonName | None = None
    sex: str | None = None
    birth_date: str | None = None
    birth_city: str | None = None
    birth_state: str | None = None
    birth_country: str | None = None
    citizenship: str | None = None
    alien_number: str | None = None


class ArrestEntry(BaseModel):
    reason: str | None = None
    date: str | None = None
    location: str | None = None
    outcome: str | None = None


class MembershipEntry(BaseModel):
    organization_name: str | None = None
    purpose: str | None = None
    from_date: str | None = None
    to_date: str | None = None


class Biographic(BaseModel):
    ethnicity: str | None = None
    races: list[str] = Field(default_factory=list)
    height_feet: int | None = None
    height_inches: int | None = None
    weight_lbs: int | None = None
    eye_color: str | None = None
    hair_color: str | None = None


class CitizenshipStatus(BaseModel):
    nationality: str | None = None
    status: str | None = None
    acquired_how: str | None = None
    certificate_number: str | None = None
    certificate_place_of_issue: str | None = None
    certificate_date_of_issue: str | None = None
    lpr_class_of_admission: str | None = None
    lpr_admit_city: str | None = None
    lpr_admit_state: str | None = None
    lpr_through_marriage: bool | None = None


class ImmigrationHistory(BaseModel):
    current_status: str | None = None
    status_expiration_date: str | None = None
    place_of_last_entry: str | None = None
    consulate_visa_issued: str | None = None
    inspected_at_entry: bool | None = None
    i765_filed: bool | None = None
    prior_petition_filed: bool | None = None
    removal_proceedings: bool | None = None
    visa_denied: bool | None = None
    visa_denied_explanation: str | None = None
    j_two_year_subject: bool | None = None
    j_complied: bool | None = None
    j_waiver: bool | None = None
    j_notes: str | None = None
    public_assistance: bool | None = None
    public_assistance_details: str | None = None


class TravelPlans(BaseModel):
    intended_departure_date: str | None = None
    trip_length_days: int | None = None
    multiple_trips: bool | None = None


class Household(BaseModel):
    size: int | None = None
    income_bracket: str | None = None
    assets_bracket: str | None = None
    liabilities_bracket: str | None = None


class Education(BaseModel):
    highest_degree: str | None = None
    certifications_licenses_skills: str | None = None
    ssi_tanf_details: str | None = None
    institutionalization_details: str | None = None


# --------------------------------------------------------------------------- #
# Role models — 1:1 with the petitioner and beneficiary questionnaires.
# --------------------------------------------------------------------------- #

class PetitionerHistory(BaseModel):
    legal_name: PersonName | None = None
    previous_names: list[PersonName] = Field(default_factory=list)
    a_number: str | None = None
    uscis_online_account_number: str | None = None
    ssn: str | None = None
    date_of_birth: str | None = None
    birth_city: str | None = None
    birth_state: str | None = None
    birth_country: str | None = None
    sex: str | None = None
    phones: PhoneNumbers | None = None
    email: str | None = None
    mailing_address: AddressEntry | None = None
    physical_address: AddressEntry | None = None
    residences_past_5_years: list[AddressEntry] = Field(default_factory=list)
    times_married: int | None = None
    current_marital_status: str | None = None
    current_spouse: SpouseInfo | None = None
    marriage_history: list[MarriageEntry] = Field(default_factory=list)
    father: ParentInfo | None = None
    mother: ParentInfo | None = None
    citizenship: CitizenshipStatus | None = None
    employment_history: list[EmploymentEntry] = Field(default_factory=list)
    biographic: Biographic | None = None
    prior_petitions_filed_details: str | None = None
    military_service_details: str | None = None
    tax_income_last_3_years: str | None = None


class BeneficiaryHistory(BaseModel):
    legal_name: PersonName | None = None
    previous_names: list[PersonName] = Field(default_factory=list)
    date_of_birth: str | None = None
    birth_city: str | None = None
    birth_state: str | None = None
    birth_country: str | None = None
    a_number: str | None = None
    ssn: str | None = None
    email: str | None = None
    phones: PhoneNumbers | None = None
    biographic: Biographic | None = None
    current_address: AddressEntry | None = None
    mailing_address: AddressEntry | None = None
    current_abroad_address: AddressEntry | None = None
    abroad_move_in_date: str | None = None
    abroad_move_out_date: str | None = None
    last_residence_outside_us: AddressEntry | None = None
    outside_us_move_in_date: str | None = None
    outside_us_move_out_date: str | None = None
    previous_addresses: list[AddressEntry] = Field(default_factory=list)
    marriage_history: list[MarriageEntry] = Field(default_factory=list)
    immigration: ImmigrationHistory | None = None
    memberships: list[MembershipEntry] = Field(default_factory=list)
    communist_party_member: bool | None = None
    communist_party_details: str | None = None
    travel: TravelPlans | None = None
    employment_history: list[EmploymentEntry] = Field(default_factory=list)
    last_abroad_employer_name: str | None = None
    last_abroad_employer_address: AddressEntry | None = None
    father: ParentInfo | None = None
    mother: ParentInfo | None = None
    children: list[ChildInfo] = Field(default_factory=list)
    arrests: list[ArrestEntry] = Field(default_factory=list)
    household: Household | None = None
    education: Education | None = None


# --------------------------------------------------------------------------- #
# Wrapper — exactly one populated role sub-model, matching `role`.
# --------------------------------------------------------------------------- #

class CaseHistoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"ch_{uuid4().hex}")
    case_id: str
    role: PartyRole
    case_number: str | None = None
    uscis_case_number: str | None = None
    case_status: str | None = None
    petitioner: PetitionerHistory | None = None
    beneficiary: BeneficiaryHistory | None = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @model_validator(mode="after")
    def _check_role_consistency(self) -> "CaseHistoryRecord":
        if self.role == "petitioner":
            if self.petitioner is None or self.beneficiary is not None:
                raise ValueError(
                    "role 'petitioner' requires petitioner set and beneficiary None"
                )
        elif self.role == "beneficiary":
            if self.beneficiary is None or self.petitioner is not None:
                raise ValueError(
                    "role 'beneficiary' requires beneficiary set and petitioner None"
                )
        return self


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _role_model(record: CaseHistoryRecord) -> BaseModel | None:
    return record.petitioner if record.role == "petitioner" else record.beneficiary


def _count_leaves(value: Any) -> int:
    """Count non-null scalar leaves in a model_dump()-style structure.

    Empty lists and None contribute nothing; every present scalar counts once.
    Used only for the PII-FREE `fields_present` metric on the event bus.
    """
    if value is None:
        return 0
    if isinstance(value, dict):
        return sum(_count_leaves(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_leaves(v) for v in value)
    return 1


def _row_to_record(row: sqlite3.Row) -> CaseHistoryRecord:
    role = row["role"]
    data = json.loads(row["data"])
    kwargs: dict[str, Any] = dict(
        id=row["id"],
        case_id=row["case_id"],
        role=role,
        case_number=row["case_number"],
        uscis_case_number=row["uscis_case_number"],
        case_status=row["case_status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    if role == "petitioner":
        kwargs["petitioner"] = PetitionerHistory.model_validate(data)
    else:
        kwargs["beneficiary"] = BeneficiaryHistory.model_validate(data)
    return CaseHistoryRecord.model_validate(kwargs)


def _get_one(
    conn: sqlite3.Connection, case_id: str, role: str
) -> CaseHistoryRecord | None:
    row = conn.execute(
        "SELECT * FROM case_history WHERE case_id = ? AND role = ?",
        (case_id, role),
    ).fetchone()
    return _row_to_record(row) if row is not None else None


def _emit_updated(
    conn: sqlite3.Connection, record: CaseHistoryRecord, actor: str
) -> None:
    """Fire the PII-FREE audit event. NEVER names/emails/values (§4.4)."""
    role_model = _role_model(record)
    fields_present = _count_leaves(role_model.model_dump()) if role_model else 0
    emit(
        conn,
        Event(
            type="case_history.updated",
            case_id=record.case_id,
            actor=actor,
            payload={
                "role": record.role,
                "fields_present": fields_present,
                "has_uscis_number": record.uscis_case_number is not None,
                "has_case_status": record.case_status is not None,
            },
        ),
    )


# --------------------------------------------------------------------------- #
# Store — module-level functions, drafts.py style.
# --------------------------------------------------------------------------- #

def next_case_number(conn: sqlite3.Connection) -> str:
    """Return the next firm case number "YIL-<YYYY>-<NNNN>" (4-digit padded).

    Atomic per-year UPSERT increment against case_history_counter.
    """
    year = str(datetime.now(timezone.utc).year)
    conn.execute(
        "INSERT INTO case_history_counter (year, seq) VALUES (?, 1) "
        "ON CONFLICT(year) DO UPDATE SET seq = seq + 1",
        (year,),
    )
    row = conn.execute(
        "SELECT seq FROM case_history_counter WHERE year = ?", (year,)
    ).fetchone()
    conn.commit()
    return f"YIL-{year}-{row['seq']:04d}"


def create_stub(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    role: PartyRole,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    case_number: str | None = None,
    actor: str = "agent:slack",
) -> CaseHistoryRecord:
    """Create a minimal record for (case_id, role): legal name + email + mobile.

    Idempotent: if a row already exists for (case_id, role), the existing record
    is returned UNCHANGED and no event fires. Everything not passed stays null —
    null over guess.
    """
    existing = _get_one(conn, case_id, role)
    if existing is not None:
        return existing

    name = PersonName(first=first_name, last=last_name)
    phones = PhoneNumbers(mobile=phone)
    if role == "petitioner":
        record = CaseHistoryRecord(
            case_id=case_id,
            role=role,
            case_number=case_number,
            petitioner=PetitionerHistory(legal_name=name, email=email, phones=phones),
        )
    else:
        record = CaseHistoryRecord(
            case_id=case_id,
            role=role,
            case_number=case_number,
            beneficiary=BeneficiaryHistory(legal_name=name, email=email, phones=phones),
        )

    _insert(conn, record)
    _emit_updated(conn, record, actor)
    return record


def _insert(conn: sqlite3.Connection, record: CaseHistoryRecord) -> None:
    role_model = _role_model(record)
    data_json = json.dumps(role_model.model_dump()) if role_model else "{}"
    conn.execute(
        "INSERT INTO case_history "
        "(id, case_id, role, case_number, uscis_case_number, case_status, "
        "data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.id,
            record.case_id,
            record.role,
            record.case_number,
            record.uscis_case_number,
            record.case_status,
            data_json,
            record.created_at,
            record.updated_at,
        ),
    )
    conn.commit()


def upsert_history(
    conn: sqlite3.Connection,
    record: CaseHistoryRecord,
    *,
    actor: str = "agent:validation",
) -> CaseHistoryRecord:
    """Nanda's form-submit path. Overwrite the current (case_id, role) record.

    Re-validates through CaseHistoryRecord before any SQL. On conflict, updates
    data/uscis_case_number/case_status and bumps updated_at; PRESERVES the existing
    case_number when the incoming one is None (COALESCE), and always preserves
    created_at. Returns the stored record read back from the DB.
    """
    record = CaseHistoryRecord.model_validate(record.model_dump())
    record = record.model_copy(update={"updated_at": _now_iso()})

    role_model = _role_model(record)
    data_json = json.dumps(role_model.model_dump()) if role_model else "{}"
    conn.execute(
        "INSERT INTO case_history "
        "(id, case_id, role, case_number, uscis_case_number, case_status, "
        "data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(case_id, role) DO UPDATE SET "
        "data = excluded.data, "
        "uscis_case_number = excluded.uscis_case_number, "
        "case_status = excluded.case_status, "
        "case_number = COALESCE(excluded.case_number, case_history.case_number), "
        "updated_at = excluded.updated_at",
        (
            record.id,
            record.case_id,
            record.role,
            record.case_number,
            record.uscis_case_number,
            record.case_status,
            data_json,
            record.created_at,
            record.updated_at,
        ),
    )
    conn.commit()

    stored = _get_one(conn, record.case_id, record.role)
    if stored is None:  # pragma: no cover - defensive; insert just succeeded
        raise RuntimeError(
            f"upsert_history lost the row for {record.case_id!r}/{record.role!r}"
        )
    _emit_updated(conn, stored, actor)
    return stored


def set_uscis(
    conn: sqlite3.Connection,
    case_id: str,
    role: PartyRole,
    *,
    uscis_case_number: str | None = None,
    case_status: str | None = None,
    actor: str = "agent:slack",
) -> CaseHistoryRecord:
    """Set the USCIS receipt number and/or case status. Fail loud if no record.

    Only the fields passed (non-None) are written; the others are preserved.
    """
    existing = _get_one(conn, case_id, role)
    if existing is None:
        raise LookupError(
            f"no case_history record for case {case_id!r} role {role!r}"
        )

    new_uscis = (
        uscis_case_number if uscis_case_number is not None
        else existing.uscis_case_number
    )
    new_status = case_status if case_status is not None else existing.case_status
    conn.execute(
        "UPDATE case_history SET uscis_case_number = ?, case_status = ?, "
        "updated_at = ? WHERE case_id = ? AND role = ?",
        (new_uscis, new_status, _now_iso(), case_id, role),
    )
    conn.commit()

    stored = _get_one(conn, case_id, role)
    if stored is None:  # pragma: no cover - defensive; existence checked above
        raise RuntimeError(
            f"set_uscis lost the row for {case_id!r}/{role!r}"
        )
    _emit_updated(conn, stored, actor)
    return stored


def get_history(
    conn: sqlite3.Connection, case_id: str, role: str | None = None
) -> list[CaseHistoryRecord]:
    """Return current records for a case, optionally filtered to one role."""
    if role is not None:
        rows = conn.execute(
            "SELECT * FROM case_history WHERE case_id = ? AND role = ? "
            "ORDER BY role ASC",
            (case_id, role),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM case_history WHERE case_id = ? ORDER BY role ASC",
            (case_id,),
        ).fetchall()
    return [_row_to_record(r) for r in rows]
