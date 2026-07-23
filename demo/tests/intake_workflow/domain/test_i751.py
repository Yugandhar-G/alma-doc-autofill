"""I-751 date math and the staff radar / scheduler alerts."""
from __future__ import annotations

from datetime import date, timedelta

from intake_workflow.domain import api


def test_i751_dates_basic():
    d = api.i751_dates(date(2024, 10, 5))
    assert d.gc_expires == date(2026, 10, 5)
    assert d.window_opens == date(2026, 10, 5) - timedelta(days=90)
    assert d.collect_docs_from == d.window_opens - timedelta(days=30)


def test_i751_dates_leap_day_rolls_to_feb_28():
    d = api.i751_dates(date(2024, 2, 29))
    assert d.gc_expires == date(2026, 2, 28)  # Feb 29 -> Feb 28
    assert d.window_opens == date(2026, 2, 28) - timedelta(days=90)
    assert d.collect_docs_from == d.window_opens - timedelta(days=30)


def _case_with_approval(new_case, store, title, approved_on):
    case = new_case(title=title, i485_approved_on=approved_on)
    store.save_case(case)
    return case


def test_i751_radar_statuses_and_sort(new_case, store, now):
    # window already open (window_opens 2026-07-07 <= now 2026-07-22)
    _case_with_approval(new_case, store, "Open", date(2024, 10, 5))
    # collect_now: window_opens 2026-08-15 (> now), collect 2026-07-16 (<= now)
    _case_with_approval(new_case, store, "Collect", date(2024, 11, 13))
    # upcoming: window far in the future
    _case_with_approval(new_case, store, "Upcoming", date(2026, 1, 1))

    radar = api.i751_radar(store, now=now)
    by_title = {r["title"]: r["status"] for r in radar}
    assert by_title["Open"] == "window_open"
    assert by_title["Collect"] == "collect_now"
    assert by_title["Upcoming"] == "upcoming"
    # Sorted soonest window first.
    windows = [r["window_opens"] for r in radar]
    assert windows == sorted(windows)
    assert radar[0]["title"] == "Open"


def test_i751_radar_ignores_cases_without_approval(new_case, store, now):
    new_case()  # no i485_approved_on
    assert api.i751_radar(store, now=now) == []


def test_run_scheduler_posts_i751_alerts_once(new_case, store, now):
    case = _case_with_approval(new_case, store, "Radar", date(2024, 10, 5))
    api.run_scheduler(store, now=now)
    kinds = [e.kind for e in store.list_timeline(case.id)]
    assert kinds.count("i751_window_open") == 1
    assert kinds.count("i751_collect_docs") == 1

    # Second tick must not duplicate the alerts.
    api.run_scheduler(store, now=now)
    kinds = [e.kind for e in store.list_timeline(case.id)]
    assert kinds.count("i751_window_open") == 1
    assert kinds.count("i751_collect_docs") == 1


def test_run_scheduler_upcoming_case_no_alert_yet(new_case, store, now):
    case = _case_with_approval(new_case, store, "Future", date(2026, 1, 1))
    api.run_scheduler(store, now=now)
    kinds = [e.kind for e in store.list_timeline(case.id)]
    assert "i751_window_open" not in kinds
    assert "i751_collect_docs" not in kinds
