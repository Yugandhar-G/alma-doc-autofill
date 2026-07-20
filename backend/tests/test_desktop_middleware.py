"""Desktop sidecar BearerTokenMiddleware — the structural ?t= download
exemption added in Phase E2.

Driven at the pure-ASGI layer with hand-built scopes (no heavy app import): we
assert only whether the request reached the downstream handler or was rejected
with a 401 by the gate. Cryptographic validation of the token is the handler's
job (covered in test_download_tokens.py), not the middleware's.
"""
import pytest

from desktop_entry import BearerTokenMiddleware

TOKEN = "per-launch-token"
ART = "/api/population-artifact/" + "b" * 64


class _Downstream:
    def __init__(self) -> None:
        self.reached = False

    async def __call__(self, scope, receive, send) -> None:
        self.reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _scope(method: str, path: str, *, query: bytes = b"", auth: str | None = None):
    headers = [(b"authorization", auth.encode())] if auth else []
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query,
        "headers": headers,
    }


async def _drive(token, scope) -> tuple[bool, int]:
    down = _Downstream()
    mw = BearerTokenMiddleware(down, token)
    status = {"code": 0}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    await mw(scope, receive, send)
    return down.reached, status["code"]


async def test_download_with_query_token_is_exempted() -> None:
    reached, _ = await _drive(TOKEN, _scope("GET", ART, query=b"download=true&t=abc123"))
    assert reached is True  # reaches the handler despite no bearer header


async def test_download_without_token_is_rejected() -> None:
    reached, status = await _drive(TOKEN, _scope("GET", ART))
    assert reached is False
    assert status == 401


async def test_query_param_named_at_does_not_bypass() -> None:
    # A param whose name merely contains 't=' must NOT be treated as a token.
    reached, status = await _drive(TOKEN, _scope("GET", ART, query=b"at=x"))
    assert reached is False
    assert status == 401


async def test_write_endpoint_without_bearer_still_rejected() -> None:
    reached, status = await _drive(TOKEN, _scope("POST", "/api/matters"))
    assert reached is False
    assert status == 401


async def test_valid_bearer_reaches_handler() -> None:
    reached, _ = await _drive(TOKEN, _scope("POST", "/api/matters", auth=f"Bearer {TOKEN}"))
    assert reached is True


async def test_options_preflight_exempted() -> None:
    reached, _ = await _drive(TOKEN, _scope("OPTIONS", "/api/matters"))
    assert reached is True


async def test_dev_mode_no_token_disables_gate() -> None:
    reached, _ = await _drive(None, _scope("POST", "/api/matters"))
    assert reached is True


async def test_token_query_on_non_artifact_path_not_exempted() -> None:
    # The exemption is scoped to the artifact route only.
    reached, status = await _drive(TOKEN, _scope("GET", "/api/matters", query=b"t=abc"))
    assert reached is False
    assert status == 401
