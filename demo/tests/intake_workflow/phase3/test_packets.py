"""Form-preparation packets. Only ACCEPTED question-section answers feed a
packet; absent/unaccepted data renders as "" and is listed under ``missing``.
Null over guess is absolute — no value is ever fabricated."""
from __future__ import annotations

import pytest

from intake_workflow.domain import api, packets
from intake_workflow.schemas import PartyRole

B = PartyRole.beneficiary


def _all_fields(packet):
    return [f for sec in packet["sections"] for f in sec["fields"]]


def _field(packet, label):
    return next(f for f in _all_fields(packet) if f["label"] == label)


# --------------------------------------------------------------------- structure

def test_build_i130_structure_and_values(accepted_case):
    packet = packets.build_packet(accepted_case, "I-130")
    assert packet["form_type"] == "I-130"
    assert packet["case_title"] == accepted_case.title
    assert [s["title"] for s in packet["sections"]] == [
        "Part 1 — Petitioner", "Part 2 — Beneficiary", "Part 3 — Marriage"]

    # Every field carries a value and an auditable source.
    for f in _all_fields(packet):
        assert set(f) == {"label", "value", "source"}
        assert "." in f["source"]

    # Values are drawn from the accepted answers, not invented.
    assert _field(packet, "Full legal name")["value"] == "Ana Marquez"
    assert _field(packet, "Full legal name")["source"] == "pet_bio.full_name"
    assert _field(packet, "Beneficiary A-number")["value"] == "A123456789"
    assert _field(packet, "Beneficiary A-number")["source"] == "ben_bio.a_number"
    assert _field(packet, "Date of marriage")["value"] == "2023-06-15"
    # Everything the two forms need is present, so nothing is missing.
    assert packet["missing"] == []


def test_build_i485_structure(accepted_case):
    packet = packets.build_packet(accepted_case, "I-485")
    assert packet["form_type"] == "I-485"
    assert [s["title"] for s in packet["sections"]] == [
        "Part 1 — Applicant", "Part 2 — Immigration history", "Part 3 — Marriage"]
    assert _field(packet, "Full legal name")["value"] == "Wei Chen"
    assert _field(packet, "Full legal name")["source"] == "ben_bio.full_name"
    assert _field(packet, "Current immigration status")["value"] == "F-1"
    assert packet["missing"] == []


# ------------------------------------------------------------------ unknown form

def test_unknown_form_type_raises_with_supported_list(accepted_case):
    with pytest.raises(ValueError) as exc:
        packets.build_packet(accepted_case, "I-765")
    msg = str(exc.value)
    assert "I-130" in msg and "I-485" in msg


# ------------------------------------------------------------- missing / unaccepted

def test_null_over_guess_all_absent(new_case):
    """A case with no accepted answers fabricates nothing: every value is "" and
    every label is listed under ``missing``."""
    packet = packets.build_packet(new_case(), "I-130")
    fields = _all_fields(packet)
    assert all(f["value"] == "" for f in fields)
    assert packet["missing"] == [f["label"] for f in fields]
    # Sources are still populated for auditability even with no data.
    assert all(f["source"] for f in fields)


def test_submitted_but_unaccepted_answers_do_not_feed_packet(new_case, store, now):
    """Accept is the data gate: a section that is only *submitted* (not accepted)
    contributes no values and its fields land in ``missing``."""
    case = new_case()
    # Submit ben_bio but never accept it -> state ``checked``, not ``accepted``.
    api.submit_answers(store, case, "ben_bio", B, {
        "full_name": "Wei Chen", "dob": "1990-02-02",
        "a_number": "A123456789", "i94_number": "AB1234567CD",
        "last_entry": "2022-01-01", "current_status": "F-1",
    }, now=now)

    packet = packets.build_packet(case, "I-130")
    assert _field(packet, "Beneficiary full legal name")["value"] == ""
    assert "Beneficiary full legal name" in packet["missing"]
    assert "Beneficiary A-number" in packet["missing"]


def test_partial_accept_lists_only_absent_fields(accepted_case, store, now):
    """With the biographic sections accepted but no A-number provided, only that
    field is missing while the rest are populated."""
    # Rebuild ben_bio acceptance without the optional A-number / I-94.
    case = accepted_case
    api.submit_answers(store, case, "ben_bio", B, {
        "full_name": "Wei Chen", "dob": "1990-02-02",
        "last_entry": "2022-01-01", "current_status": "F-1",
    }, now=now)
    api.review_item(store, case, "ben_bio", action="accepted", reviewer="Isaiah",
                    now=now)

    packet = packets.build_packet(case, "I-130")
    assert _field(packet, "Beneficiary A-number")["value"] == ""
    assert "Beneficiary A-number" in packet["missing"]
    assert "Beneficiary I-94 number" in packet["missing"]
    # A required, provided field is still populated.
    assert _field(packet, "Beneficiary full legal name")["value"] == "Wei Chen"
