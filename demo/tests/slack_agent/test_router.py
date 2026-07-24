"""Router tests — poller pickup + dual-path dedup by event id.

Also covers the router-owned intake.validated completeness notification
("validate → if yes → tell the caseworker"): it must ride the SAME dual
pubsub+poller dedupe path as draft.created, post exactly once, and fire only on
complete=true.
"""

from __future__ import annotations

import json

from core.events import emit
from core.models import Event
from slack_agent import router as router_mod, threads
from slack_agent.router import EventRouter
from seed import seed_case

CASE_NAME = "Ravi Kumar / Mei Lin"  # seeded case display name


async def _drain(router: EventRouter) -> None:
    while not router.queue.empty():
        await router.dispatch(router.queue.get_nowait())


def _recording_router(db):
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.id)

    router = EventRouter(db, {"draft.created": handler})
    return router, seen


def _notify_router(db, slack) -> EventRouter:
    """Router wired with a fake Slack client so the intake.validated handler is
    registered (it rides the same handlers dict → subscribe + poll + dedupe)."""
    return EventRouter(db, {}, client=slack, fallback_channel="C_CASES")


def _validated_event(complete: bool) -> Event:
    return Event(
        type="intake.validated",
        case_id=seed_case.CASE_ID,
        actor="agent:validation",
        payload={"complete": complete, "missing": []},
    )


def test_dispatch_dedupes_same_event(db, run):
    router, seen = _recording_router(db)
    ev = Event(type="draft.created", case_id="c", actor="agent:validation", payload={})
    emit(db, ev)
    run(router.dispatch(ev))
    run(router.dispatch(ev))  # second time: already claimed, skipped
    assert seen == [ev.id]


def test_poller_picks_up_cross_process_events_and_advances_high_water(db, run):
    router, seen = _recording_router(db)
    # Emitted by "another process" — no in-process subscriber fired.
    e1 = emit(db, Event(type="draft.created", case_id="c", actor="agent:validation", payload={}))
    e2 = emit(db, Event(type="draft.created", case_id="c", actor="agent:validation", payload={}))
    router.poll_once()
    run(_drain(router))
    assert seen == [e1.id, e2.id]
    # A second poll after handling finds nothing new (high-water advanced).
    router.poll_once()
    run(_drain(router))
    assert seen == [e1.id, e2.id]


def test_subscriber_and_poller_post_once(db, run):
    router, seen = _recording_router(db)
    router.subscribe()  # path (a): in-process pubsub
    # emit() fires the subscriber synchronously → enqueues once.
    ev = emit(db, Event(type="draft.created", case_id="c", actor="agent:slack", payload={}))
    # path (b): poller sees the same row and enqueues it again.
    router.poll_once()
    run(_drain(router))
    # Both paths enqueued it, but dedup claims it once → handled once.
    assert seen == [ev.id]


def test_only_registered_types_are_polled(db, run):
    router, seen = _recording_router(db)
    emit(db, Event(type="intake.sent", case_id="c", actor="agent:validation", payload={}))
    router.poll_once()
    run(_drain(router))
    assert seen == []


# --------------------------------------------------------------------------- #
# Feature 1 — intake.validated completeness notification
# --------------------------------------------------------------------------- #

def test_intake_validated_complete_posts_into_mapped_thread(db, slack, run):
    seed_case.seed(db)
    threads.map_thread(db, seed_case.CASE_ID, "C1", "42.0")
    router = _notify_router(db, slack)

    emit(db, _validated_event(complete=True))
    router.poll_once()
    run(_drain(router))

    assert len(slack.posts) == 1
    post = slack.posts[0]
    assert post["channel"] == "C1"
    assert post["thread_ts"] == "42.0"
    blob = json.dumps(post["blocks"])
    assert "Ready to file" in blob  # verdict card replaces the passive ping
    assert CASE_NAME in blob  # case name rendered
    assert "Isaiah" in blob  # default caseworker mention


def test_intake_validated_complete_dedupes_across_pubsub_and_poller(db, slack, run):
    seed_case.seed(db)
    threads.map_thread(db, seed_case.CASE_ID, "C1", "42.0")
    router = _notify_router(db, slack)
    router.subscribe()  # path (a): in-process pubsub for intake.validated

    # emit() fires the subscriber synchronously → enqueues once.
    emit(db, _validated_event(complete=True))
    # path (b): poller sees the same row and enqueues it again.
    router.poll_once()
    run(_drain(router))

    # Both paths enqueued it; dedup claims it once → posted EXACTLY once.
    assert len(slack.posts) == 1


def test_intake_validated_incomplete_posts_nothing(db, slack, run):
    seed_case.seed(db)
    threads.map_thread(db, seed_case.CASE_ID, "C1", "42.0")
    router = _notify_router(db, slack)

    emit(db, _validated_event(complete=False))
    router.poll_once()
    run(_drain(router))

    assert slack.posts == []


def test_intake_validated_falls_back_to_channel_when_unmapped(db, slack, run):
    seed_case.seed(db)  # no thread mapping recorded
    router = _notify_router(db, slack)

    emit(db, _validated_event(complete=True))
    router.poll_once()
    run(_drain(router))

    assert len(slack.posts) == 1
    assert slack.posts[0]["channel"] == "C_CASES"
    assert slack.posts[0]["thread_ts"] is None


def test_caseworker_mention_uses_configured_handle(db, slack, run, monkeypatch):
    seed_case.seed(db)
    threads.map_thread(db, seed_case.CASE_ID, "C1", "42.0")
    # The module constant is the env-derived handle; overriding it stands in for
    # SLACK_CASEWORKER_HANDLE being set.
    monkeypatch.setattr(router_mod, "CASEWORKER_HANDLE", "@paralegal-team")
    router = _notify_router(db, slack)

    emit(db, _validated_event(complete=True))
    router.poll_once()
    run(_drain(router))

    assert "@paralegal-team" in json.dumps(slack.posts[0]["blocks"])


def test_caseworker_handle_constant_reads_env(monkeypatch):
    """The module constant is populated from SLACK_CASEWORKER_HANDLE, falling
    back to 'Isaiah' when unset."""
    import importlib

    monkeypatch.setenv("SLACK_CASEWORKER_HANDLE", "@ops-desk")
    try:
        reloaded = importlib.reload(router_mod)
        assert reloaded.CASEWORKER_HANDLE == "@ops-desk"
    finally:
        monkeypatch.undo()
        importlib.reload(router_mod)  # restore default for later tests
