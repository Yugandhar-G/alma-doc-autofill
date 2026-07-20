"""In-process rate limiting — a fixed-window counter keyed by (firm_id, route
class).

Desktop reality: the kernel runs as a single sidecar process on one machine, so
in-memory counters are the correct and sufficient enforcement point — there is
no second node to coordinate with. The seam for a future multi-node server is a
shared backend (Redis INCR + EX, or a token-bucket Lua script) behind the same
`RateLimiter.check` signature; nothing above this module would change.

Strict limits guard the write / run-start / auth-adjacent endpoints (matter
create, document upload, run start/resume, screener session create,
ask-the-matter). Reads stay unthrottled — the dependency is simply not attached
to them.

A breach raises `RateLimitError`, mapped to a 429 in the standard ApiResponse
envelope by `install_rate_limit`. Enforcement is disabled wholesale when
`settings.rate_limit_enabled` is False (tests, or a deliberate opt-out).
"""
import logging
import threading
import time
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.kernel.auth import Principal, get_principal
from app.kernel.config import Settings, get_settings
from app.schemas import ApiResponse

logger = logging.getLogger("yunaki.kernel.ratelimit")

_WINDOW_SECONDS = 60  # fixed window; the per-min cap is the settings knob


class RateLimitError(Exception):
    """A firm exceeded its window budget. One type, mapped to 429. The message
    is a fixed, generic string — it names no firm and leaks no counts."""


class RateLimiter:
    """Fixed-window counter. `check(key, limit)` returns whether the call is
    allowed and, if so, records it. Thread-safe (a TestClient may drive
    requests off a worker thread)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (window_start, count)
        self._buckets: dict[tuple[str, str], tuple[float, int]] = {}

    def check(self, key: tuple[str, str], limit: int) -> bool:
        now = self._clock()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= _WINDOW_SECONDS:
                window_start, count = now, 0  # window rolled over
            if count >= limit:
                return False
            self._buckets[key] = (window_start, count + 1)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# Process-wide singleton — the counters ARE the shared state for the single
# sidecar. Tests reset it between cases (autouse fixture in tests/conftest.py).
_LIMITER = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _LIMITER


def reset_rate_limits() -> None:
    """Clear all counters — used by tests to isolate cases."""
    _LIMITER.reset()


def rate_limit(
    route_class: str = "write",
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Dependency factory gating a route to the firm's per-window write budget.

    Keyed by (principal.firm_id, route_class) so one firm's burst never starves
    another's, and so read/write classes count independently. No-ops when
    disabled. Reuses the request's already-resolved Principal (FastAPI caches
    Depends within a request), so this adds no extra auth work."""

    async def _dependency(
        principal: Principal = Depends(get_principal),
        settings: Settings = Depends(get_settings),
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        key = (principal.firm_id, route_class)
        if not _LIMITER.check(key, settings.rate_limit_writes_per_min):
            # firm_id stays out of the log line (PII/tenancy) — count only.
            logger.warning("rate limit exceeded route_class=%s", route_class)
            raise RateLimitError("rate limit exceeded — slow down and retry shortly")

    return _dependency


def install_rate_limit(app: FastAPI) -> None:
    """Register the RateLimitError → 429 handler, in the ApiResponse envelope."""

    @app.exception_handler(RateLimitError)
    async def _rate_limit_handler(_: Request, exc: RateLimitError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=ApiResponse(success=False, error=str(exc)).model_dump(),
        )
