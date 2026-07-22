"""Router tests — poller pickup + dual-path dedup by event id."""

from __future__ import annotations

from core.events import emit
from core.models import Event
from slack_agent.router import EventRouter


async def _drain(router: EventRouter) -> None:
    while not router.queue.empty():
        await router.dispatch(router.queue.get_nowait())


def _recording_router(db):
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.id)

    router = EventRouter(db, {"draft.created": handler})
    return router, seen


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
