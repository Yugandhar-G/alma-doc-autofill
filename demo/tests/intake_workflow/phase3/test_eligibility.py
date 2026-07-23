"""Eligibility red-flag screening, the submit_answers hook, the attorney queue,
and sign-off. Red flags are attorney-only and never alter the client flow."""
from __future__ import annotations

from datetime import timedelta

import pytest

from intake_workflow.domain import api, eligibility
from intake_workflow.schemas import CheckStatus, ItemState, PartyRole

B = PartyRole.beneficiary


def _elig(**over):
    base = {"criminal_history": "No", "immigration_violations": "No",
            "prior_denials": "No"}
    base.update(over)
    return base


# ------------------------------------------------------------------- screen_answers

def test_screen_flags_each_yes_key_with_details_verbatim(new_case, now):
    case = new_case()
    item = case.item("ben_eligibility")
    answers = {
        "criminal_history": "Yes", "criminal_details": "DUI, 2015.",
        "immigration_violations": "Yes",
        "violation_details": "Overstayed a B-2 visa by 3 months in 2019.",
        "prior_denials": "Yes", "denial_details": "B-2 refused in 2018.",
    }
    findings = eligibility.screen_answers(item, answers, now)
    codes = {f.code for f in findings}
    assert codes == {"criminal_history", "immigration_violations", "prior_denials"}
    joined = " || ".join(f.message for f in findings)
    assert "DUI, 2015." in joined
    assert "Overstayed a B-2 visa by 3 months in 2019." in joined
    assert "B-2 refused in 2018." in joined


def test_screen_yes_without_details_still_flags(new_case, now):
    case = new_case()
    findings = eligibility.screen_answers(
        case.item("ben_eligibility"),
        _elig(criminal_history="Yes"), now)
    assert [f.code for f in findings] == ["criminal_history"]
    assert findings[0].message == "Criminal history disclosed"  # no trailing details


def test_screen_is_case_insensitive_on_yes(new_case, now):
    case = new_case()
    findings = eligibility.screen_answers(
        case.item("ben_eligibility"), _elig(prior_denials="yes"), now)
    assert [f.code for f in findings] == ["prior_denials"]


def test_screen_ignores_all_no_missing_and_non_eligibility(new_case, now):
    case = new_case()
    elig = case.item("ben_eligibility")
    assert eligibility.screen_answers(elig, _elig(), now) == []      # all "No"
    assert eligibility.screen_answers(elig, {}, now) == []           # missing keys
    # A non-eligibility item has no red-flag fields, so even a stray "Yes" is ignored.
    assert eligibility.screen_answers(
        case.item("pet_bio"), {"criminal_history": "Yes"}, now) == []


def test_screen_never_raises_on_odd_input(new_case, now):
    case = new_case()
    elig = case.item("ben_eligibility")
    # Empty answers, and a None value, must not raise.
    assert eligibility.screen_answers(elig, {"criminal_history": None}, now) == []


# --------------------------------------------------- submit_answers hook (parity)

def test_submit_yes_flags_without_changing_client_flow(new_case, store, now):
    yes_case = new_case()
    no_case = new_case(title="Control — all No")

    yes_item = api.submit_answers(
        store, yes_case, "ben_eligibility", B,
        _elig(immigration_violations="Yes",
              violation_details="Overstayed a B-2 visa by 3 months in 2019."),
        now=now)
    no_item = api.submit_answers(
        store, no_case, "ben_eligibility", B, _elig(), now=now)

    # Client-visible flow is byte-for-byte the same: state + autocheck.
    assert yes_item.state == no_item.state == ItemState.checked
    assert yes_item.submissions[-1].autocheck.status == CheckStatus.passed
    assert no_item.submissions[-1].autocheck.status == CheckStatus.passed
    assert yes_item.submissions[-1].autocheck.findings == []

    # Attorney-only additions on the flagged case.
    assert yes_item.attorney_review is True
    assert [f.code for f in yes_item.submissions[-1].internal_flags] == \
        ["immigration_violations"]
    yes_kinds = [e.kind for e in store.list_timeline(yes_case.id)]
    assert "attorney_review_flagged" in yes_kinds

    # The control case is untouched by the attorney machinery.
    assert no_item.attorney_review is False
    assert no_item.submissions[-1].internal_flags == []
    assert "attorney_review_flagged" not in \
        [e.kind for e in store.list_timeline(no_case.id)]


def test_flagged_timeline_summary_is_neutral(new_case, store, now):
    case = new_case()
    api.submit_answers(
        store, case, "ben_eligibility", B,
        _elig(criminal_history="Yes", criminal_details="DUI, 2015."), now=now)
    flagged = next(e for e in store.list_timeline(case.id)
                   if e.kind == "attorney_review_flagged")
    # Neutral summary — no flag details; codes live in data only.
    assert flagged.summary == "Background questions routed to attorney review"
    assert "DUI" not in flagged.summary
    assert "criminal" not in flagged.summary.lower()
    assert flagged.data["codes"] == ["criminal_history"]


# --------------------------------------------------------------- attorney_queue

def test_attorney_queue_lists_flagged_items_oldest_first(new_case, store, now):
    earlier = now - timedelta(days=2)
    case_old = new_case(title="Older flag")
    case_new = new_case(title="Newer flag")
    api.submit_answers(store, case_old, "ben_eligibility", B,
                       _elig(criminal_history="Yes"), now=earlier)
    api.submit_answers(store, case_new, "ben_eligibility", B,
                       _elig(prior_denials="Yes"), now=now)

    queue = eligibility.attorney_queue(store)
    assert [r["case_id"] for r in queue] == [case_old.id, case_new.id]
    row = queue[0]
    assert row["item_key"] == "ben_eligibility"
    assert row["item_label"] == case_old.item("ben_eligibility").label
    assert row["since"] == earlier
    assert row["flags"] == ["Criminal history disclosed"]


def test_attorney_queue_excludes_unflagged_cases(new_case, store, now):
    case = new_case()
    api.submit_answers(store, case, "ben_eligibility", B, _elig(), now=now)
    assert eligibility.attorney_queue(store) == []


# ------------------------------------------------------------ clear_attorney_review

def test_clear_attorney_review_clears_and_timelines(new_case, store, now):
    case = new_case()
    api.submit_answers(store, case, "ben_eligibility", B,
                       _elig(criminal_history="Yes"), now=now)
    item = eligibility.clear_attorney_review(
        store, case, "ben_eligibility", reviewer="Dana",
        note="Reviewed — old DUI, no bar to eligibility.", now=now)
    assert item.attorney_review is False
    assert store.get_case(case.id).item("ben_eligibility").attorney_review is False
    cleared = next(e for e in store.list_timeline(case.id)
                   if e.kind == "attorney_cleared")
    assert cleared.data["reviewer"] == "Dana"
    assert cleared.data["note"] == "Reviewed — old DUI, no bar to eligibility."
    # It drops off the queue.
    assert eligibility.attorney_queue(store) == []


def test_clear_attorney_review_not_flagged_raises_valueerror(new_case, store, now):
    case = new_case()
    api.submit_answers(store, case, "ben_eligibility", B, _elig(), now=now)
    with pytest.raises(ValueError):
        eligibility.clear_attorney_review(store, case, "ben_eligibility",
                                          reviewer="Dana", now=now)


def test_clear_attorney_review_unknown_item_raises_keyerror(new_case, store, now):
    case = new_case()
    with pytest.raises(KeyError):
        eligibility.clear_attorney_review(store, case, "no_such_item",
                                          reviewer="Dana", now=now)
