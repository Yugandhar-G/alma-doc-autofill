"""Offline tests for the USCIS case-status tool — no network.

Coverage:
- receipt validation rejects garbage BEFORE any driver call;
- fixture driver returns the seeded statuses (and normalizes casing/dashes);
- unknown-but-valid receipt ⇒ {"status":"not_found"};
- live driver against a hand-rolled httpx.MockTransport: the OAuth token call
  and the case-status call go ONLY to the allow-listed base, a 200 is parsed
  faithfully, a 404 ⇒ not_found, and a non-200 ⇒ a loud error (never a
  fabricated status), a 401 triggers exactly one token refresh + retry.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agents.tools_uscis import (
    UscisConfig,
    _live_driver,
    build_uscis_case_status_tool,
    normalize_receipt,
)

_ALLOWED_HOST = "api-int.uscis.gov"
_LIVE_CFG = UscisConfig(
    api_base="https://api-int.uscis.gov", client_id="cid", client_secret="csecret"
)


def _dispatch(tool, args: dict, ctx) -> dict[str, Any]:
    import asyncio

    return json.loads(asyncio.run(tool.run(args, ctx)))


# --------------------------------------------------------------------------- #
# Receipt validation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "garbage",
    [
        "hello",
        "EAC123",
        "eac25900123",          # too short
        "1234567890123",        # 13 chars, no letter prefix
        "ZZZ1234567890",        # well-shaped but unknown prefix
        "EAC25900123456",       # 11 digits
        "",
        "'; DROP TABLE case;--",
    ],
)
def test_rejects_garbage_before_any_driver_call(garbage, make_ctx, run):
    calls: list[str] = []

    async def spy(receipt: str) -> dict:
        calls.append(receipt)
        return {"kind": "found", "source": "fixture", "status_title": "x"}

    tool = build_uscis_case_status_tool(driver=spy)
    ctx, _events = make_ctx()

    result = _dispatch(tool, {"receipt_number": garbage}, ctx)

    assert result["status"] == "invalid_receipt"
    assert calls == []  # driver was never reached — no network was possible


def test_normalize_receipt_canonicalizes():
    assert normalize_receipt("eac2590012345") == "EAC2590012345"
    assert normalize_receipt(" ioe-0912-345678 ") == "IOE0912345678"
    assert normalize_receipt("nope") is None


# --------------------------------------------------------------------------- #
# Fixture driver
# --------------------------------------------------------------------------- #

def test_fixture_driver_returns_seeded_statuses(make_ctx):
    tool = build_uscis_case_status_tool(UscisConfig())  # no creds ⇒ fixture
    ctx, events = make_ctx()

    result = _dispatch(tool, {"receipt_number": "IOE0912345678"}, ctx)

    assert result["receipt_number"] == "IOE0912345678"
    assert result["status_title"] == "Case Was Received"
    assert "Form I-130" in result["status_detail"]
    assert result["last_updated"] == "2026-07-18"
    assert result["source"] == "fixture"
    assert result["fetched_at"]  # timestamped
    assert any(e.get("tool") == "get_uscis_case_status" for e in events)


def test_fixture_driver_normalizes_lowercase_input(make_ctx):
    tool = build_uscis_case_status_tool(UscisConfig())
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "wac2190054321"}, ctx)

    assert result["receipt_number"] == "WAC2190054321"
    assert result["status_title"] == "Case Was Approved"
    assert result["source"] == "fixture"


def test_unknown_valid_receipt_is_not_found(make_ctx):
    tool = build_uscis_case_status_tool(UscisConfig())
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "IOE0000000000"}, ctx)

    assert result == {"receipt_number": "IOE0000000000", "status": "not_found"}
    assert "status_title" not in result  # never a fabricated status


# --------------------------------------------------------------------------- #
# Live driver against a fake transport
# --------------------------------------------------------------------------- #

def _make_transport(records: list[dict], *, status_handler):
    """MockTransport recording every request; routes token + status paths."""

    def handler(request: httpx.Request) -> httpx.Response:
        records.append(
            {
                "url": str(request.url),
                "host": request.url.host,
                "scheme": request.url.scheme,
                "method": request.method,
                "content": request.content.decode() if request.content else "",
            }
        )
        if request.url.path == "/oauth/accesstoken":
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={"access_token": "tok-123", "token_type": "Bearer", "expires_in": 1799},
            )
        if request.url.path.startswith("/case-status/"):
            return status_handler(request)
        return httpx.Response(404, json={"code": 404, "message": "no route"})

    return httpx.MockTransport(handler)


def _live_tool(records, *, status_handler):
    transport = _make_transport(records, status_handler=status_handler)

    async def driver(receipt: str) -> dict:
        return await _live_driver(receipt, _LIVE_CFG, transport=transport)

    return build_uscis_case_status_tool(_LIVE_CFG, driver=driver)


def _assert_only_allowlisted(records: list[dict]) -> None:
    assert records, "no requests were made"
    for rec in records:
        assert rec["host"] == _ALLOWED_HOST, f"off-allowlist host: {rec['host']}"
        assert rec["scheme"] == "https"


def test_live_driver_success_hits_only_allowlisted_base(make_ctx):
    records: list[dict] = []

    def status_ok(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok-123"
        return httpx.Response(
            200,
            json={
                "case_status": {
                    "receiptNumber": "EAC2590012345",
                    "formType": "I-130",
                    "modifiedDate": "09-05-2026 14:28:46",
                    "current_case_status_text_en": "Case Was Approved",
                    "current_case_status_desc_en": "On September 5, 2026, we approved your Form I-130.",
                },
                "message": "Query was successful",
            },
        )

    tool = _live_tool(records, status_handler=status_ok)
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "EAC2590012345"}, ctx)

    assert result["source"] == "uscis_api"
    assert result["status_title"] == "Case Was Approved"
    assert result["status_detail"].startswith("On September 5, 2026")
    assert result["last_updated"] == "09-05-2026 14:28:46"
    assert result["receipt_number"] == "EAC2590012345"

    # Exactly the token call then the status call, both on the allow-listed host.
    _assert_only_allowlisted(records)
    paths = [httpx.URL(r["url"]).path for r in records]
    assert paths == ["/oauth/accesstoken", "/case-status/EAC2590012345"]
    # Credentials went in the token body form, not the status URL.
    token_body = records[0]["content"]
    assert "grant_type=client_credentials" in token_body
    assert "client_id=cid" in token_body and "client_secret=csecret" in token_body
    assert "csecret" not in records[1]["url"]


def test_live_driver_404_is_not_found(make_ctx):
    records: list[dict] = []

    def status_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": 404, "message": "not found"})

    tool = _live_tool(records, status_handler=status_404)
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "EAC2590012345"}, ctx)

    assert result == {"receipt_number": "EAC2590012345", "status": "not_found"}
    _assert_only_allowlisted(records)


def test_live_driver_non200_is_loud_never_fabricated(make_ctx):
    records: list[dict] = []

    def status_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": 500, "message": "boom"})

    tool = _live_tool(records, status_handler=status_500)
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "EAC2590012345"}, ctx)

    assert result["status"] == "error"
    assert "HTTP 500" in result["detail"]
    assert "status_title" not in result  # no fabricated status on failure
    _assert_only_allowlisted(records)


def test_live_driver_token_failure_is_loud(make_ctx):
    """A failed token call ⇒ error, and the status endpoint is never reached."""
    records: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        records.append({"path": request.url.path, "host": request.url.host})
        if request.url.path == "/oauth/accesstoken":
            return httpx.Response(401, json={"code": 401, "message": "bad creds"})
        return httpx.Response(200, json={"case_status": {}})

    transport = httpx.MockTransport(handler)

    async def driver(receipt: str) -> dict:
        return await _live_driver(receipt, _LIVE_CFG, transport=transport)

    tool = build_uscis_case_status_tool(_LIVE_CFG, driver=driver)
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "EAC2590012345"}, ctx)

    assert result["status"] == "error"
    assert result["detail"] == "token request failed"
    assert [r["path"] for r in records] == ["/oauth/accesstoken"]  # no status call


def test_live_driver_401_triggers_single_refresh_then_succeeds(make_ctx):
    records: list[dict] = []
    state = {"status_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        records.append({"path": request.url.path, "host": request.url.host})
        if request.url.path == "/oauth/accesstoken":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 1799})
        state["status_calls"] += 1
        if state["status_calls"] == 1:
            return httpx.Response(401, json={"code": 401, "message": "expired"})
        return httpx.Response(
            200,
            json={"case_status": {"current_case_status_text_en": "Case Was Received"}},
        )

    transport = httpx.MockTransport(handler)

    async def driver(receipt: str) -> dict:
        return await _live_driver(receipt, _LIVE_CFG, transport=transport)

    tool = build_uscis_case_status_tool(_LIVE_CFG, driver=driver)
    ctx, _ = make_ctx()

    result = _dispatch(tool, {"receipt_number": "EAC2590012345"}, ctx)

    assert result["status_title"] == "Case Was Received"
    assert result["source"] == "uscis_api"
    # token, status(401), token(refresh), status(200)
    assert [r["path"] for r in records] == [
        "/oauth/accesstoken",
        "/case-status/EAC2590012345",
        "/oauth/accesstoken",
        "/case-status/EAC2590012345",
    ]
    for rec in records:
        assert rec["host"] == _ALLOWED_HOST
