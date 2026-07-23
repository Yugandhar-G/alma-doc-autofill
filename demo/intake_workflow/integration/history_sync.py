"""history_sync — accepted intake answers flow into our typed case_history.

When the intake app's paralegal ACCEPTS a ``question_section`` item, the answers
on that item's latest submission are mapped into our shared ``case_history``
record for the case (petitioner or beneficiary, per the item's assignee).

Discipline (mirrors the extraction contract):
  - Only fields the form actually provided are set; everything else on the
    existing record is preserved (we copy the existing role model and touch only
    the mapped paths).
  - Empty / whitespace answers become ``None`` — a null is correct, a guess is a
    defect. Free-text addresses go WHOLE into ``AddressEntry.street`` (we never
    parse city/state/zip out of a blob).
  - We never CREATE case_history here: no mapping or no existing record ->
    log loudly and return (the stub is created upstream at handoff).

FROZEN field mapping (his ``item.key`` + field -> our model path). UNMAPPED
answers are intentional and documented in docs/integration-bridge.md:
  pet_bio.full_name          -> PetitionerHistory.legal_name (split)
  pet_bio.dob                -> PetitionerHistory.date_of_birth
  pet_bio.phone              -> PetitionerHistory.phones.mobile
  pet_bio.address            -> PetitionerHistory.physical_address.street (whole)
  marriage_details.marriage_date  -> one current MarriageEntry.marriage_date
  marriage_details.marriage_place -> that MarriageEntry.marriage_city (whole)
  marriage_details.prior_marriages -> UNMAPPED (count-only select, no typed target)
  ben_bio.full_name          -> BeneficiaryHistory.legal_name (split)
  ben_bio.dob                -> BeneficiaryHistory.date_of_birth
  ben_bio.a_number           -> BeneficiaryHistory.a_number
  ben_bio.current_status     -> BeneficiaryHistory.immigration.current_status
  ben_bio.i94_number         -> UNMAPPED (no honest typed target)
  ben_bio.last_entry         -> UNMAPPED (no honest typed target)
  ben_address_history.current_address  -> current_address.street (whole)
  ben_address_history.moved_in         -> current_address.from_date
  ben_address_history.previous_address -> previous_addresses=[AddressEntry(street)]
  ben_eligibility.criminal_history=="Yes"     -> arrests=[ArrestEntry(reason=details)]
  ben_eligibility.prior_denials=="Yes"        -> immigration.visa_denied=True (+expl)
  ben_eligibility.immigration_violations      -> UNMAPPED (attorney queue owns it)
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("intake_workflow.integration.history_sync")


def _clean(value: Any) -> str | None:
    """Trim a raw answer to a non-empty string, or None. Never returns ''."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_name(full: str):
    """first token -> first, remainder joined -> last, single token -> first only.

    Never invents a middle name. Caller passes an already-non-empty string.
    """
    from core.case_history import PersonName

    parts = full.split()
    if not parts:
        return PersonName()
    if len(parts) == 1:
        return PersonName(first=parts[0])
    return PersonName(first=parts[0], last=" ".join(parts[1:]))


def _latest_answers(item) -> dict | None:
    """Answers from the item's latest submission that actually carries answers."""
    for submission in reversed(item.submissions):
        if submission.answers:
            return submission.answers
    return None


def _other_party_full_name(store_case, assignee) -> str | None:
    """Full name of the party that is NOT the item's assignee (the spouse)."""
    for party in store_case.parties:
        if party.role != assignee:
            return _clean(party.full_name)
    return None


# --------------------------------------------------------------------------- #
# Per-item mappers. Each takes the current role model + cleaned answers and
# returns a NEW role model (immutably) with only provided fields set.
# --------------------------------------------------------------------------- #

def _map_pet_bio(role_model, ans: dict):
    from core.case_history import AddressEntry, PhoneNumbers

    updates: dict[str, Any] = {}
    if (full := _clean(ans.get("full_name"))):
        updates["legal_name"] = _split_name(full)
    if (dob := _clean(ans.get("dob"))):
        updates["date_of_birth"] = dob
    if (phone := _clean(ans.get("phone"))):
        base = role_model.phones or PhoneNumbers()
        updates["phones"] = base.model_copy(update={"mobile": phone})
    if (addr := _clean(ans.get("address"))):
        base = role_model.physical_address or AddressEntry()
        updates["physical_address"] = base.model_copy(update={"street": addr})
    return role_model.model_copy(update=updates) if updates else role_model


def _map_marriage_details(role_model, ans: dict, store_case, assignee):
    from core.case_history import MarriageEntry

    marriage_date = _clean(ans.get("marriage_date"))
    marriage_place = _clean(ans.get("marriage_place"))
    if not (marriage_date or marriage_place):
        return role_model

    other_full = _other_party_full_name(store_case, assignee)
    spouse_name = _split_name(other_full) if other_full else None
    entry = MarriageEntry(
        marriage_date=marriage_date,
        marriage_city=marriage_place,
        current=True,
        spouse_name=spouse_name,
    )
    return role_model.model_copy(update={"marriage_history": [entry]})


def _map_ben_bio(role_model, ans: dict):
    from core.case_history import ImmigrationHistory

    updates: dict[str, Any] = {}
    if (full := _clean(ans.get("full_name"))):
        updates["legal_name"] = _split_name(full)
    if (dob := _clean(ans.get("dob"))):
        updates["date_of_birth"] = dob
    if (a_number := _clean(ans.get("a_number"))):
        updates["a_number"] = a_number
    if (status := _clean(ans.get("current_status"))):
        base = role_model.immigration or ImmigrationHistory()
        updates["immigration"] = base.model_copy(update={"current_status": status})
    return role_model.model_copy(update=updates) if updates else role_model


def _map_ben_address_history(role_model, ans: dict):
    from core.case_history import AddressEntry

    updates: dict[str, Any] = {}
    current_updates: dict[str, Any] = {}
    if (street := _clean(ans.get("current_address"))):
        current_updates["street"] = street
    if (moved_in := _clean(ans.get("moved_in"))):
        current_updates["from_date"] = moved_in
    if current_updates:
        base = role_model.current_address or AddressEntry()
        updates["current_address"] = base.model_copy(update=current_updates)
    if (previous := _clean(ans.get("previous_address"))):
        updates["previous_addresses"] = [AddressEntry(street=previous)]
    return role_model.model_copy(update=updates) if updates else role_model


def _map_ben_eligibility(role_model, ans: dict):
    from core.case_history import ArrestEntry, ImmigrationHistory

    updates: dict[str, Any] = {}
    if ans.get("criminal_history") == "Yes":
        updates["arrests"] = [ArrestEntry(reason=_clean(ans.get("criminal_details")))]
    if ans.get("prior_denials") == "Yes":
        base = role_model.immigration or ImmigrationHistory()
        updates["immigration"] = base.model_copy(
            update={
                "visa_denied": True,
                "visa_denied_explanation": _clean(ans.get("denial_details")),
            }
        )
    return role_model.model_copy(update=updates) if updates else role_model


def _apply_mapping(item, role_model, ans: dict, store_case, assignee):
    """Dispatch on item.key; unknown keys are a no-op (return unchanged model)."""
    if item.key == "pet_bio":
        return _map_pet_bio(role_model, ans)
    if item.key == "marriage_details":
        return _map_marriage_details(role_model, ans, store_case, assignee)
    if item.key == "ben_bio":
        return _map_ben_bio(role_model, ans)
    if item.key == "ben_address_history":
        return _map_ben_address_history(role_model, ans)
    if item.key == "ben_eligibility":
        return _map_ben_eligibility(role_model, ans)
    return role_model


def sync_accepted_item(store_case, item) -> None:
    """Map an accepted question_section item's answers into our case_history.

    Never creates a case or a history stub; logs loudly and returns when the
    mapping or the existing record is missing.
    """
    from intake_workflow.integration import config

    if not config.enabled():
        return

    from core.case_history import get_history, upsert_history

    role = item.assignee.value  # "petitioner" | "beneficiary"

    conn = config.shared_conn()
    try:
        core_case_id = config.core_case_for(conn, store_case.id)
        if core_case_id is None:
            _log.warning(
                "history_sync: no case mapping for local case %s; skipping item %s",
                store_case.id, item.key,
            )
            return

        records = get_history(conn, core_case_id, role=role)
        if not records:
            _log.warning(
                "history_sync: no %s case_history record for core case %s; "
                "skipping item %s (stub should exist from handoff)",
                role, core_case_id, item.key,
            )
            return
        existing = records[0]

        answers = _latest_answers(item)
        if not answers:
            return

        role_key = "petitioner" if role == "petitioner" else "beneficiary"
        role_model = getattr(existing, role_key)
        updated_model = _apply_mapping(item, role_model, answers, store_case, item.assignee)

        # case_number=None so upsert_history preserves the existing firm number
        # (its COALESCE); id/created_at are preserved by the ON CONFLICT update.
        updated_record = existing.model_copy(
            update={role_key: updated_model, "case_number": None}
        )
        upsert_history(conn, updated_record, actor="agent:validation")
    finally:
        conn.close()
