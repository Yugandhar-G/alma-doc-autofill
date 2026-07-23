"""Fixtures and test doubles for the email agent's suite.

Mirrors the minimal domain fixtures (store / now / new_case) so these tests do
not depend on tests/domain/conftest.py, and provides the two email provider
doubles the task calls for:

- ``FakeProvider``  — records every send() call and returns a canned id.
- ``FailingProvider`` — always raises EmailSendError.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intake_workflow.domain import api
from intake_workflow.email.outbox import EmailSendError
from intake_workflow.store import Store

# Same fixed instant the domain suite uses, for deterministic ladder math.
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


class FakeProvider:
    """EmailProvider double that records calls and returns a stable id."""

    def __init__(self, name: str = "fake", message_id: str = "fake-msg-1") -> None:
        self.name = name
        self._message_id = message_id
        self.calls: list[dict[str, str]] = []

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        self.calls.append({"to_email": to_email, "subject": subject, "body": body})
        return self._message_id


class FailingProvider:
    """EmailProvider double that always fails the send."""

    name = "failing"

    def __init__(self, message: str = "simulated send failure") -> None:
        self._message = message
        self.calls: list[dict[str, str]] = []

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        self.calls.append({"to_email": to_email, "subject": subject, "body": body})
        raise EmailSendError(self._message)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


@pytest.fixture
def new_case(store, now):
    """Factory creating a fresh marriage-AOS case (all items pending)."""
    def _make(**overrides):
        params = dict(
            title="Marquez ↔ Chen — Marriage AOS",
            petitioner_name="Ana Marquez",
            petitioner_email="p@example.com",
            beneficiary_name="Wei Chen",
            beneficiary_email="b@example.com",
        )
        params.update(overrides)
        return api.create_case(store, now=now, **params)
    return _make
