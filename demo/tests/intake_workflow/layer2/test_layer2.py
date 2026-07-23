"""Layer-2 cross-document checks — flag-only, null over guess, no network.

Every test drives ``layer2.run_layer2`` with a canned ``FakeExtractor`` and
asserts the exact state rules from the frozen ``run_layer2`` docstring.
"""
from __future__ import annotations

from intake_workflow.domain import layer2
from intake_workflow.schemas import CheckStatus, ItemState

from tests.intake_workflow.layer2.conftest import NOW, FakeExtractor

# Labels layer-2 passes to the extractor as ``doc_hint`` (from the template).
MARRIAGE_CERT = "Marriage certificate"
BEN_PASSPORT = "Beneficiary — Passport bio page"
LEASE = "Lease or deed with both names"

MATCH_BOTH = {"person_names": ["Ana Marquez", "Wei Chen"],
              "document_type": "Marriage Certificate"}


def _codes(item):
    return [f.code for f in item.submissions[-1].autocheck.findings]


# --------------------------------------------------------------- scope rules

def test_accepted_and_returned_items_never_touched(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.accepted)
    attach_doc(case, "lease", state=ItemState.returned)

    extractor = FakeExtractor(default=None)  # would flag anything it sees
    checked = layer2.run_layer2(store, case, extractor, now=NOW)

    assert checked == []
    assert extractor.calls == []  # never extracted a decided item
    assert case.item("marriage_cert").state == ItemState.accepted
    assert case.item("lease").state == ItemState.returned


def test_question_sections_skipped(new_case, attach_answers, store):
    case = new_case()
    attach_answers(case, "pet_bio",
                   {"full_name": "Ana Marquez", "dob": "1988-04-12"},
                   state=ItemState.checked)

    extractor = FakeExtractor(default=None)
    checked = layer2.run_layer2(store, case, extractor, now=NOW)

    assert checked == []
    assert extractor.calls == []
    # A question section keeps its state and gets no layer-2 autocheck written.
    assert case.item("pet_bio").state == ItemState.checked
    assert case.item("pet_bio").submissions[-1].autocheck is None


def test_document_without_stored_file_skipped(new_case, store):
    case = new_case()
    # checked doc item but no submission at all -> nothing to extract
    case.item("marriage_cert").state = ItemState.checked
    store.save_case(case)

    extractor = FakeExtractor(default=MATCH_BOTH)
    checked = layer2.run_layer2(store, case, extractor, now=NOW)

    assert checked == []
    assert extractor.calls == []


# ------------------------------------------------------------ clean pass path

def test_clean_pass_leaves_checked_unchanged_and_appends_passed_result(
    new_case, attach_doc, store
):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={MARRIAGE_CERT: MATCH_BOTH})
    checked = layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    assert [i.key for i in checked] == ["marriage_cert"]
    assert item.state == ItemState.checked  # unchanged on a clean pass
    autocheck = item.submissions[-1].autocheck
    assert autocheck is not None
    assert autocheck.layer == 2
    assert autocheck.status == CheckStatus.passed
    assert autocheck.findings == []


# --------------------------------------------------------------- flag paths

def test_name_mismatch_flags_a_checked_item(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={MARRIAGE_CERT: {"person_names": ["Roberto Silva"]}})
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    assert item.state == ItemState.flagged
    assert "name_mismatch" in _codes(item)
    assert item.submissions[-1].autocheck.status == CheckStatus.flagged


def test_middle_name_does_not_trip_name_mismatch(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)

    # A middle name on the document must still match the expected spouse.
    extractor = FakeExtractor(by_hint={
        MARRIAGE_CERT: {"person_names": ["Ana Sofia Marquez", "Wei Chen"]}
    })
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    assert item.state == ItemState.checked
    assert "name_mismatch" not in _codes(item)


def test_lease_with_one_name_flags(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "lease", state=ItemState.checked)

    # Only one spouse on the lease -> the other is unconfirmed.
    extractor = FakeExtractor(by_hint={LEASE: {"person_names": ["Ana Marquez"]}})
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("lease")
    assert item.state == ItemState.flagged
    assert "missing_spouse_name" in _codes(item)
    # The one present name matches a spouse, so no generic name mismatch.
    assert "name_mismatch" not in _codes(item)


def test_lease_with_both_names_passes(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "lease", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={
        LEASE: {"person_names": ["Ana Marquez", "Wei Chen"],
                "document_type": "Residential Lease Agreement"}
    })
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("lease")
    assert item.state == ItemState.checked
    assert item.submissions[-1].autocheck.findings == []


def test_expired_expiry_date_flags(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "ben_passport", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={
        BEN_PASSPORT: {"person_names": ["Wei Chen"], "expiry_date": "2020-01-01"}
    })
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("ben_passport")
    assert item.state == ItemState.flagged
    assert "expired_document" in _codes(item)


def test_future_expiry_date_does_not_flag(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "ben_passport", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={
        BEN_PASSPORT: {"person_names": ["Wei Chen"], "expiry_date": "2030-01-01"}
    })
    layer2.run_layer2(store, case, extractor, now=NOW)

    assert case.item("ben_passport").state == ItemState.checked


def test_document_type_mismatch_flags(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={
        MARRIAGE_CERT: {"person_names": ["Ana Marquez", "Wei Chen"],
                        "document_type": "Utility Bill"}
    })
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    assert item.state == ItemState.flagged
    assert "document_type_mismatch" in _codes(item)


def test_extractor_none_result_flags_could_not_verify(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)

    extractor = FakeExtractor(default=None)  # extraction failed / unreadable
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    assert item.state == ItemState.flagged
    assert _codes(item) == ["could_not_verify"]


def test_flagged_item_stays_flagged(new_case, attach_doc, store):
    case = new_case()
    # Item already flagged by layer 1; layer 2 finds an issue too.
    attach_doc(case, "marriage_cert", state=ItemState.flagged)

    extractor = FakeExtractor(default=None)
    checked = layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    assert item in checked  # flagged items are in scope
    assert item.state == ItemState.flagged
    assert "could_not_verify" in _codes(item)


def test_flagged_item_with_clean_pass_stays_flagged(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.flagged)

    extractor = FakeExtractor(by_hint={MARRIAGE_CERT: MATCH_BOTH})
    layer2.run_layer2(store, case, extractor, now=NOW)

    item = case.item("marriage_cert")
    # A clean layer-2 pass never un-flags — state is left unchanged.
    assert item.state == ItemState.flagged
    assert item.submissions[-1].autocheck.status == CheckStatus.passed


# --------------------------------------------------- persistence & timeline

def test_timeline_events_written(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)
    attach_doc(case, "lease", state=ItemState.checked)

    extractor = FakeExtractor(
        by_hint={MARRIAGE_CERT: MATCH_BOTH,
                 LEASE: {"person_names": ["Ana Marquez"]}}
    )
    layer2.run_layer2(store, case, extractor, now=NOW)

    events = [e for e in store.list_timeline(case.id) if e.kind == "layer2_checked"]
    assert len(events) == 2
    by_item = {e.data["item"]: e for e in events}
    assert by_item["marriage_cert"].data["findings"] == []
    assert by_item["lease"].data["findings"] == ["missing_spouse_name"]
    assert all(e.data["layer"] == 2 for e in events)


def test_case_is_persisted(new_case, attach_doc, store):
    case = new_case()
    attach_doc(case, "marriage_cert", state=ItemState.checked)

    extractor = FakeExtractor(default=None)
    layer2.run_layer2(store, case, extractor, now=NOW)

    # Reload from the store — the layer-2 result and state must have persisted.
    reloaded = store.get_case(case.id)
    item = reloaded.item("marriage_cert")
    assert item.state == ItemState.flagged
    assert item.submissions[-1].autocheck.layer == 2
    assert item.submissions[-1].autocheck.status == CheckStatus.flagged


def test_expected_names_include_bio_answers(new_case, attach_doc, attach_answers, store):
    case = new_case()
    # A document naming only the biographic-questionnaire answer, not the
    # party record, must still match (bio full_name feeds the expected set).
    attach_answers(case, "ben_bio",
                   {"full_name": "Wei Ling Chen", "dob": "1990-02-02"},
                   state=ItemState.checked)
    attach_doc(case, "ben_passport", state=ItemState.checked)

    extractor = FakeExtractor(by_hint={BEN_PASSPORT: {"person_names": ["Wei Ling Chen"]}})
    layer2.run_layer2(store, case, extractor, now=NOW)

    assert case.item("ben_passport").state == ItemState.checked
    assert "name_mismatch" not in _codes(case.item("ben_passport"))
