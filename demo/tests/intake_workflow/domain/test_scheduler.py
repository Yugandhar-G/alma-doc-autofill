"""Follow-up scheduler: ladder selection, dedupe, reset-on-activity, idempotence."""
from __future__ import annotations

from datetime import timedelta

from intake_workflow.domain import api
from intake_workflow.schemas import OutreachStatus, PartyRole, Rung

B = PartyRole.beneficiary


def _stalled_case(new_case, store, now, days):
    """Fresh case whose beneficiary last acted ``days`` ago (open pending items)."""
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=days)
    store.save_case(case)
    return case


def _bene_drafts(drafted):
    return [o for o in drafted if o.party_role == B]


def test_ladder_nudge_at_day_3(new_case, store, now):
    _stalled_case(new_case, store, now, 3)
    drafted = _bene_drafts(api.run_scheduler(store, now=now))
    assert len(drafted) == 1
    assert drafted[0].rung == Rung.nudge


def test_ladder_specifics_at_day_7(new_case, store, now):
    _stalled_case(new_case, store, now, 8)
    drafted = _bene_drafts(api.run_scheduler(store, now=now))
    assert len(drafted) == 1
    assert drafted[0].rung == Rung.specifics


def test_ladder_call_offer_at_day_12(new_case, store, now):
    _stalled_case(new_case, store, now, 13)
    drafted = _bene_drafts(api.run_scheduler(store, now=now))
    assert drafted[0].rung == Rung.call_offer


def test_ladder_escalate_at_day_18(new_case, store, now):
    _stalled_case(new_case, store, now, 20)
    drafted = _bene_drafts(api.run_scheduler(store, now=now))
    assert drafted[0].rung == Rung.escalate


def test_below_first_rung_drafts_nothing(new_case, store, now):
    _stalled_case(new_case, store, now, 2)  # < day 3
    assert api.run_scheduler(store, now=now) == []


def test_only_parties_with_open_required_items_get_followups(new_case, store, now,
                                                             make_pdf):
    # Accept every beneficiary-assigned item so the beneficiary has nothing open,
    # even though they are long inactive.
    case = new_case()
    from intake_workflow.schemas import ItemKind
    from .conftest import VALID_ANSWERS
    for item in [i for i in case.items if i.assignee == B]:
        if item.kind == ItemKind.question_section:
            api.submit_answers(store, case, item.key, B, VALID_ANSWERS[item.key], now=now)
        else:
            api.submit_document(store, case, item.key, B, "f.pdf", make_pdf(), now=now)
        api.review_item(store, case, item.key, action="accepted", reviewer="Isaiah",
                        now=now)
    case.party(B).last_activity_at = now - timedelta(days=30)
    store.save_case(case)
    drafted = _bene_drafts(api.run_scheduler(store, now=now))
    assert drafted == []


def test_dedupe_same_tick_and_second_run_idempotent(new_case, store, now):
    _stalled_case(new_case, store, now, 5)
    first = api.run_scheduler(store, now=now)
    assert _bene_drafts(first)
    # Immediate second tick at the same instant drafts nothing new.
    second = api.run_scheduler(store, now=now)
    assert second == []
    # And a later tick (still no activity) does not re-draft the same rung.
    later = api.run_scheduler(store, now=now + timedelta(days=1))
    assert _bene_drafts(later) == []


def test_activity_resets_the_ladder(new_case, store, now):
    case = _stalled_case(new_case, store, now, 5)
    assert _bene_drafts(api.run_scheduler(store, now=now))  # nudge drafted at `now`

    # Client visits the portal -> ladder resets to their new activity time.
    case = store.get_case(case.id)
    api.record_activity(store, case, B, now)

    # Right after activity there is nothing to send (day 0).
    assert api.run_scheduler(store, now=now) == []

    # After a fresh inactivity gap a new nudge fires again (reset, not deduped).
    reset_drafts = _bene_drafts(api.run_scheduler(store, now=now + timedelta(days=3)))
    assert len(reset_drafts) == 1
    assert reset_drafts[0].rung == Rung.nudge


def test_scheduler_persists_outreach_and_timeline(new_case, store, now):
    case = _stalled_case(new_case, store, now, 5)
    drafted = api.run_scheduler(store, now=now)
    reloaded = store.get_case(case.id)
    ids = {o.id for o in reloaded.outreach}
    assert drafted[0].id in ids
    assert reloaded.outreach[0].status == OutreachStatus.drafted
    assert "outreach_drafted" in [e.kind for e in store.list_timeline(case.id)]
