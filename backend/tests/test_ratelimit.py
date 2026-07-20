"""Rate limiting — the in-process fixed-window limiter and its wiring onto the
write/run-start endpoints.

Unit tests drive RateLimiter directly with an injected clock; HTTP tests reuse
the matter-API harness (tmp store + tmp WorkflowService) with a small per-min
cap so a short burst trips the window. The autouse reset fixture in conftest.py
clears the process-wide counters between cases.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.matters import get_workflow_service
from app.kernel.config import Settings, get_settings
from app.kernel.ratelimit import RateLimiter, rate_limit  # noqa: F401 (import wiring)
from app.kernel.runtime.workflows import WorkflowService
from app.kernel.store.base import get_matter_store
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.main import create_app
from app.packages.preflight.package import PACKAGE as PREFLIGHT_PACKAGE


# --- Unit: fixed-window counter --------------------------------------------
class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_limiter_allows_up_to_limit_then_denies() -> None:
    clock = _Clock()
    limiter = RateLimiter(clock=clock)
    key = ("firm-1", "write")
    assert [limiter.check(key, 3) for _ in range(3)] == [True, True, True]
    assert limiter.check(key, 3) is False  # 4th in the window


def test_limiter_window_rolls_over() -> None:
    clock = _Clock()
    limiter = RateLimiter(clock=clock)
    key = ("firm-1", "write")
    assert limiter.check(key, 1) is True
    assert limiter.check(key, 1) is False
    clock.t = 61.0  # past the 60s window
    assert limiter.check(key, 1) is True


def test_limiter_isolates_keys() -> None:
    limiter = RateLimiter(clock=_Clock())
    assert limiter.check(("firm-1", "write"), 1) is True
    assert limiter.check(("firm-1", "write"), 1) is False
    # A different firm — and a different route class — have independent budgets.
    assert limiter.check(("firm-2", "write"), 1) is True
    assert limiter.check(("firm-1", "read"), 1) is True


# --- HTTP wiring -----------------------------------------------------------
def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        matter_store_path=str(tmp_path / "matters.db"),
        preflight_checkpoint_path=str(tmp_path / "preflight.db"),
        local_storage_dir=str(tmp_path / "blobs"),
        **overrides,
    )


def _client(settings: Settings):
    store = SqliteMatterStore(settings)
    service = WorkflowService(store, (PREFLIGHT_PACKAGE,), settings=settings)
    app = create_app(registry=(PREFLIGHT_PACKAGE,))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_matter_store] = lambda: store
    app.dependency_overrides[get_workflow_service] = lambda: service
    return TestClient(app)


def _create(client):
    return client.post("/api/matters", json={"matter_type": "immigration", "title": "M"})


def test_write_burst_past_window_returns_429(tmp_path: Path) -> None:
    client = _client(_settings(tmp_path, rate_limit_enabled=True, rate_limit_writes_per_min=3))
    codes = [_create(client).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    body = _create(client).json()  # still throttled
    assert body["success"] is False
    assert body["error"]


def test_reads_are_unthrottled(tmp_path: Path) -> None:
    client = _client(_settings(tmp_path, rate_limit_enabled=True, rate_limit_writes_per_min=2))
    # Exhaust the write budget first.
    for _ in range(3):
        _create(client)
    # Reads keep working regardless of the write window state.
    for _ in range(10):
        assert client.get("/api/matters").status_code == 200


def test_disabled_flag_bypasses_limiter(tmp_path: Path) -> None:
    client = _client(_settings(tmp_path, rate_limit_enabled=False, rate_limit_writes_per_min=1))
    codes = [_create(client).status_code for _ in range(5)]
    assert codes == [200] * 5


def test_429_uses_apiresponse_envelope(tmp_path: Path) -> None:
    client = _client(_settings(tmp_path, rate_limit_enabled=True, rate_limit_writes_per_min=1))
    _create(client)
    resp = _create(client)
    assert resp.status_code == 429
    body = resp.json()
    assert set(body) >= {"success", "data", "error"}
    assert body["success"] is False
