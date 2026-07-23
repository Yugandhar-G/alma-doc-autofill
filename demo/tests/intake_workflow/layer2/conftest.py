"""Fixtures for the layer-2 suite.

Layer-2 tests never touch the network: a ``FakeExtractor`` returns canned
dicts keyed by the checklist item's label (the ``doc_hint`` layer-2 passes).
Cases are built through the real domain ``create_case`` so item keys, parties,
and template structure stay faithful; document submissions are attached
directly (no real files needed — the extractor is faked).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intake_workflow.domain import api
from intake_workflow.schemas import (
    ItemState,
    ReviewAction,
    Submission,
)
from intake_workflow.store import Store

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


class FakeExtractor:
    """Canned, network-free extractor.

    ``by_hint`` maps a checklist label -> the dict (or None) to return for it;
    ``default`` is returned for anything unmapped. Records ``calls`` so tests
    can assert which items were (and were not) extracted.
    """

    name = "fake"

    def __init__(self, default=None, by_hint=None):
        self._default = default
        self._by_hint = dict(by_hint or {})
        self.calls: list[tuple[str, str]] = []

    def extract(self, stored_path, doc_hint):
        self.calls.append((stored_path, doc_hint))
        if doc_hint in self._by_hint:
            return self._by_hint[doc_hint]
        return self._default


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


@pytest.fixture
def new_case(store):
    def _make(**overrides):
        params = dict(
            title="Marquez ↔ Chen — Marriage AOS",
            petitioner_name="Ana Marquez",
            petitioner_email="p@example.com",
            beneficiary_name="Wei Chen",
            beneficiary_email="b@example.com",
        )
        params.update(overrides)
        return api.create_case(store, now=NOW, **params)
    return _make


@pytest.fixture
def attach_doc(store):
    """Attach a document submission to ``item_key`` and set its state, then
    persist. Returns the item."""
    def _attach(case, item_key, state=ItemState.checked,
                filename=None, stored_path=None):
        item = case.item(item_key)
        filename = filename or f"{item_key}.pdf"
        stored_path = stored_path or f"/uploads/{filename}"
        item.submissions.append(
            Submission(submitted_at=NOW, filename=filename, stored_path=stored_path)
        )
        item.state = state
        if state == ItemState.accepted:
            item.reviews.append(
                ReviewAction(action="accepted", reviewer="Isaiah", at=NOW)
            )
        elif state == ItemState.returned:
            item.reviews.append(
                ReviewAction(action="returned", reason="Please re-upload.",
                             reviewer="Isaiah", at=NOW)
            )
        store.save_case(case)
        return item
    return _attach


@pytest.fixture
def attach_answers(store):
    """Attach a question_section answers submission to ``item_key``."""
    def _attach(case, item_key, answers, state=ItemState.checked):
        item = case.item(item_key)
        item.submissions.append(
            Submission(submitted_at=NOW, answers=dict(answers))
        )
        item.state = state
        store.save_case(case)
        return item
    return _attach
