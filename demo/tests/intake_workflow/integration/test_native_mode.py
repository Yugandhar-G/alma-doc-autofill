"""Native-mode reality checks (replaces the old opt-in ``disabled`` suite).

The opt-in ``YUNAKI_SHARED_DB`` mode is GONE: the integration is native in the
monorepo. ``enabled()`` is unconditionally True, ``shared_conn()`` resolves to
the single ``core.config.get_db_path()`` DB, and the default email provider is
the firm's Slack-approved SendgateProvider. Only ``"none"`` opts out to a
record-only provider.
"""
from __future__ import annotations

import sqlite3


def test_config_reports_always_enabled():
    from intake_workflow.integration import config

    # Native: no env toggles this off anymore.
    assert config.enabled() is True


def test_shared_conn_resolves_to_db_path(tmp_path, monkeypatch):
    """shared_conn() opens the one monorepo DB at core.config.get_db_path()."""
    db_path = str(tmp_path / "monorepo.db")
    monkeypatch.setenv("DB_PATH", db_path)

    from core.config import get_db_path
    from intake_workflow.integration import config

    assert get_db_path() == db_path
    conn = config.shared_conn()
    try:
        assert isinstance(conn, sqlite3.Connection)
        # The connection is the DB_PATH file: a row written here is visible
        # through a second plain connection to the same path.
        config.ensure_tables(conn)
        conn.execute(
            "INSERT OR IGNORE INTO iw_case_map (yew_case_id, core_case_id, created_at) "
            "VALUES ('local-1', 'core-1', '2026-07-23T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    check = sqlite3.connect(db_path)
    try:
        row = check.execute(
            "SELECT core_case_id FROM iw_case_map WHERE yew_case_id = 'local-1'"
        ).fetchone()
        assert row is not None and row[0] == "core-1"
    finally:
        check.close()


def test_get_provider_defaults_to_sendgate(monkeypatch):
    """Unset env -> the firm's Slack-approved SendgateProvider (new default)."""
    monkeypatch.delenv("YUNAKI_EMAIL_PROVIDER", raising=False)
    from intake_workflow.email.outbox import get_provider
    from intake_workflow.integration.sendgate_provider import SendgateProvider

    provider = get_provider()
    assert isinstance(provider, SendgateProvider)
    assert provider.name == "sendgate"


def test_get_provider_empty_string_defaults_to_sendgate(monkeypatch):
    monkeypatch.setenv("YUNAKI_EMAIL_PROVIDER", "")
    from intake_workflow.email.outbox import get_provider
    from intake_workflow.integration.sendgate_provider import SendgateProvider

    assert isinstance(get_provider(), SendgateProvider)


def test_get_provider_none_opts_out_to_record_only(monkeypatch):
    """The explicit "none" value is the only way back to record-only sends."""
    monkeypatch.setenv("YUNAKI_EMAIL_PROVIDER", "none")
    from intake_workflow.email.outbox import get_provider

    assert get_provider() is None
