"""SendgateProvider: sends become pending drafts on our gated pipeline."""
from __future__ import annotations

import pytest

from intake_workflow.email.outbox import EmailSendError


def _query_events(conn, **kwargs):
    from core.events import query_events

    return query_events(conn, **kwargs)


def test_get_provider_resolves_sendgate(bridge_env, monkeypatch):
    monkeypatch.setenv("YUNAKI_EMAIL_PROVIDER", "sendgate")
    from intake_workflow.email.outbox import get_provider
    from intake_workflow.integration.sendgate_provider import SendgateProvider

    provider = get_provider()
    assert isinstance(provider, SendgateProvider)
    assert provider.name == "sendgate"


def test_known_email_creates_pending_draft_and_event(bridge_env, core_conn, seed):
    info = seed()
    from intake_workflow.integration.sendgate_provider import SendgateProvider

    provider = SendgateProvider()
    message_id = provider.send(
        to_email=info["petitioner_email"],
        subject="We need one more document",
        body="Hi Ravi, please upload the lease.",
    )

    # Returns the synthetic id keyed on the draft.
    assert message_id.startswith("sendgate-")
    draft_id = message_id[len("sendgate-"):]

    # A pending draft exists on our side, tied to the resolved /core case.
    row = core_conn.execute(
        "SELECT case_id, kind, trigger, to_name, to_channel_address, state "
        "FROM draft WHERE id = ?",
        (draft_id,),
    ).fetchone()
    assert row is not None
    assert row["case_id"] == info["case_id"]
    assert row["kind"] == "client_email"
    assert row["trigger"] == "manual"
    assert row["to_name"] == "Ravi Kumar"
    assert row["to_channel_address"] == info["petitioner_email"]
    assert row["state"] == "pending"

    # A draft.created event was emitted for the case.
    events = _query_events(core_conn, case_id=info["case_id"], type="draft.created")
    assert len(events) == 1
    assert events[0].payload["draft_id"] == draft_id
    assert events[0].payload["channel"] == "client_email"
    assert events[0].actor == "agent:validation"

    # NOTHING was actually sent.
    sent = core_conn.execute("SELECT COUNT(*) AS n FROM message_sent").fetchone()
    assert sent["n"] == 0


def test_unknown_email_raises_and_creates_no_draft(bridge_env, core_conn, seed):
    seed()
    from intake_workflow.integration.sendgate_provider import SendgateProvider

    provider = SendgateProvider()
    with pytest.raises(EmailSendError):
        provider.send(
            to_email="stranger@nowhere.test", subject="s", body="b"
        )

    n = core_conn.execute("SELECT COUNT(*) AS n FROM draft").fetchone()["n"]
    assert n == 0
