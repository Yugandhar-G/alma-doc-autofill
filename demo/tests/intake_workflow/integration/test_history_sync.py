"""history_sync: accepted question_section answers -> typed case_history.

Driven through Nanda's real review flow (submit_answers -> review_item accept)
so the review_item wire-up is exercised end to end.
"""
from __future__ import annotations

import json

from intake_workflow.domain import api
from intake_workflow.schemas import PartyRole


def _setup(his_store, core_conn, seed):
    info = seed()
    from intake_workflow.integration import config

    his_case = api.create_case(
        his_store,
        title="History Sync Case",
        petitioner_name="Ravi Kumar",
        petitioner_email=info["petitioner_email"],
        beneficiary_name="Mei Lin",
        beneficiary_email=info["beneficiary_email"],
    )
    config.map_case(core_conn, his_case.id, info["case_id"])
    return info, his_case


def _submit_and_accept(his_store, case, item_key, role, answers):
    api.submit_answers(his_store, case, item_key, role, answers)
    api.review_item(his_store, case, item_key, action="accepted", reviewer="Allison")


def _petitioner(core_conn, case_id):
    from core.case_history import get_history

    return get_history(core_conn, case_id, role="petitioner")[0]


def _beneficiary(core_conn, case_id):
    from core.case_history import get_history

    return get_history(core_conn, case_id, role="beneficiary")[0]


def test_pet_bio_maps_and_preserves_identity(bridge_env, his_store, core_conn, seed):
    info, case = _setup(his_store, core_conn, seed)

    _submit_and_accept(
        his_store, case, "pet_bio", PartyRole.petitioner,
        {
            "full_name": "Ravi Kumar",
            "dob": "1990-05-01",
            "phone": "+1-555-9999",
            "address": "123 Main St, San Jose, CA 95101",
        },
    )

    rec = _petitioner(core_conn, info["case_id"])
    pet = rec.petitioner
    assert pet.legal_name.first == "Ravi"
    assert pet.legal_name.last == "Kumar"
    assert pet.date_of_birth == "1990-05-01"
    assert pet.phones.mobile == "+1-555-9999"
    # Free-text address goes WHOLE into street; no city/state/zip parsing.
    assert pet.physical_address.street == "123 Main St, San Jose, CA 95101"
    assert pet.physical_address.city is None
    assert pet.physical_address.zip_postal is None
    # Stub identity + firm case number preserved.
    assert rec.id == info["stub_ids"]["petitioner"]
    assert rec.case_number == info["case_number"]


def test_marriage_details_builds_current_marriage(bridge_env, his_store, core_conn, seed):
    info, case = _setup(his_store, core_conn, seed)

    _submit_and_accept(
        his_store, case, "marriage_details", PartyRole.petitioner,
        {
            "marriage_date": "2025-11-08",
            "marriage_place": "San Jose, California",
            "prior_marriages": "None",
        },
    )

    pet = _petitioner(core_conn, info["case_id"]).petitioner
    assert len(pet.marriage_history) == 1
    entry = pet.marriage_history[0]
    assert entry.marriage_date == "2025-11-08"
    assert entry.marriage_city == "San Jose, California"
    assert entry.current is True
    # Spouse = the OTHER party (beneficiary), split not invented.
    assert entry.spouse_name.first == "Mei"
    assert entry.spouse_name.last == "Lin"


def test_ben_bio_empty_string_becomes_null_and_unmapped_absent(
    bridge_env, his_store, core_conn, seed
):
    info, case = _setup(his_store, core_conn, seed)

    _submit_and_accept(
        his_store, case, "ben_bio", PartyRole.beneficiary,
        {
            "full_name": "Mei Lin",
            "dob": "1992-02-02",
            "a_number": "   ",              # whitespace -> None
            "current_status": "F-1",
            "i94_number": "12345678901",    # UNMAPPED
            "last_entry": "2020-01-01",     # UNMAPPED
        },
    )

    rec = _beneficiary(core_conn, info["case_id"])
    ben = rec.beneficiary
    assert ben.legal_name.first == "Mei"
    assert ben.date_of_birth == "1992-02-02"
    assert ben.a_number is None            # whitespace never stored as ""
    assert ben.immigration.current_status == "F-1"
    # UNMAPPED answers must not leak anywhere in the typed record.
    dumped = json.dumps(ben.model_dump())
    assert "12345678901" not in dumped
    assert "2020-01-01" not in dumped
    assert rec.id == info["stub_ids"]["beneficiary"]


def test_ben_eligibility_red_flags_map(bridge_env, his_store, core_conn, seed):
    info, case = _setup(his_store, core_conn, seed)

    # Establish an immigration status first, then layer eligibility onto it.
    _submit_and_accept(
        his_store, case, "ben_bio", PartyRole.beneficiary,
        {"full_name": "Mei Lin", "dob": "1992-02-02", "current_status": "F-1"},
    )
    _submit_and_accept(
        his_store, case, "ben_eligibility", PartyRole.beneficiary,
        {
            "criminal_history": "Yes",
            "criminal_details": "Cited for jaywalking, 2015",
            "immigration_violations": "Yes",
            "violation_details": "Overstayed by 20 days",
            "prior_denials": "Yes",
            "denial_details": "B1/B2 refused 2018",
        },
    )

    ben = _beneficiary(core_conn, info["case_id"]).beneficiary
    assert len(ben.arrests) == 1
    assert ben.arrests[0].reason == "Cited for jaywalking, 2015"
    assert ben.immigration.visa_denied is True
    assert ben.immigration.visa_denied_explanation == "B1/B2 refused 2018"
    # Prior ben_bio value preserved across the eligibility upsert.
    assert ben.immigration.current_status == "F-1"
    # immigration_violations is UNMAPPED (attorney queue owns it).
    dumped = json.dumps(ben.model_dump())
    assert "Overstayed by 20 days" not in dumped


def test_document_and_nonaccepted_items_do_not_write(
    bridge_env, his_store, core_conn, seed
):
    from core.events import query_events

    info, case = _setup(his_store, core_conn, seed)

    before = len(query_events(core_conn, case_id=info["case_id"], type="case_history.updated"))

    # A document item accepted -> hook skips (kind != question_section).
    api.review_item(his_store, case, "marriage_cert", action="accepted", reviewer="Allison")
    # A question_section returned (not accepted) -> no sync write.
    api.submit_answers(
        his_store, case, "marriage_details", PartyRole.petitioner,
        {"marriage_date": "2025-11-08", "marriage_place": "San Jose", "prior_marriages": "None"},
    )
    api.review_item(
        his_store, case, "marriage_details", action="returned",
        reviewer="Allison", reason="Please attach the certificate.",
    )

    after = len(query_events(core_conn, case_id=info["case_id"], type="case_history.updated"))
    assert after == before
    # Petitioner marriage history stayed empty (nothing was accepted).
    assert _petitioner(core_conn, info["case_id"]).petitioner.marriage_history == []
