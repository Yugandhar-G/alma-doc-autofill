"""USCIS live case-status tool — a granted tool of the @yunaki deep agent.

One kernel ToolSpec, `get_uscis_case_status(receipt_number)`, behind two
interchangeable drivers:

- **live driver** — OAuth2 client-credentials against the official USCIS Case
  Status API (developer.uscis.gov). Selected when USCIS_CLIENT_ID +
  USCIS_CLIENT_SECRET are set.
- **fixture driver** — a small seeded receipt→status map (fictional receipts,
  thematically aligned with the seeded Ravi Kumar / Mei Lin marriage case).
  The default when credentials are absent, so the demo runs fully offline.

API shape verified against the developer.uscis.gov OpenAPI spec (mid-2026):
  - token:  POST {base}/oauth/accesstoken  (form: grant_type/client_id/client_secret)
  - status: GET  {base}/case-status/{receiptNumber}  (Authorization: Bearer <token>)
  - 200 body: case_status.current_case_status_text_en / current_case_status_desc_en
  - 404 = unknown receipt, 401 = token expired (one refresh + retry).
  Docs: https://developer.uscis.gov/api/case-status
        https://developer.uscis.gov/article/how-get-access-tokens-client-credentials

GUARDRAIL DISCIPLINE (CLAUDE_WORKPLAN.md §4.3): the tool NEVER invents a status.
An unknown receipt or an API miss returns {"status":"not_found"}; a transport or
HTTP error returns a loud {"status":"error", ...} — never a fabricated status and
never an estimated timeline. The description instructs the model to report "not
on file" on not_found and to state ONLY the status text the API returned.

Network discipline (SSRF, simplified from kernel.tools.guards): the only caller
input is the receipt number, structurally validated (3 letters + 10 digits,
known prefix) BEFORE any network call. Every request URL is built from
USCIS_API_BASE alone and re-checked to be https on the pinned host — the tool
never fetches a caller-supplied URL. follow_redirects is off; timeouts are set;
one token refresh only, no other retries.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

# registry + genai import cleanly on any interpreter with the yunaki backend on
# the path (they need only google.genai + pydantic-settings, not deepagents).
from google.genai import types as genai_types

from app.kernel.tools.registry import ToolContext, ToolSpec

logger = logging.getLogger("yunaki.agents.uscis")

# Sandbox base (verified developer.uscis.gov OpenAPI spec, mid-2026). The
# production host is issued by USCIS per grant and injected via USCIS_API_BASE —
# never guessed in code.
DEFAULT_API_BASE = "https://api-int.uscis.gov"
_TOKEN_PATH = "/oauth/accesstoken"
_STATUS_PATH = "/case-status"
_TIMEOUT_S = 10.0

# Receipt = 3 letters + 10 digits. Prefix allow-list = documented USCIS service
# centers + ELIS online filing (IOE). Anything else is rejected BEFORE any call.
_RECEIPT_RE = re.compile(r"^[A-Z]{3}[0-9]{10}$")
_KNOWN_PREFIXES = frozenset(
    {"IOE", "EAC", "WAC", "LIN", "SRC", "MSC", "YSC", "NBC", "NSC", "VSC", "TSC", "CSC"}
)

# Driver contract: receipt (already validated) -> outcome dict with a "kind" of
# "found" | "not_found" | "error". Both drivers speak exactly this.
Driver = Callable[[str], Awaitable[dict[str, Any]]]


# --------------------------------------------------------------------------- #
# Receipt validation (runs before any driver / network)
# --------------------------------------------------------------------------- #

def normalize_receipt(raw: str) -> str | None:
    """Upper-case, strip separators, and validate. Returns the canonical receipt
    (e.g. "EAC2590012345") or None if it is not a valid USCIS receipt number."""
    receipt = (raw or "").strip().upper().replace("-", "").replace(" ", "")
    if not _RECEIPT_RE.match(receipt):
        return None
    if receipt[:3] not in _KNOWN_PREFIXES:
        return None
    return receipt


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class UscisConfig:
    api_base: str = DEFAULT_API_BASE
    client_id: str | None = None
    client_secret: str | None = None

    @property
    def has_creds(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def host(self) -> str:
        return urlparse(self.api_base).hostname or ""

    @property
    def token_url(self) -> str:
        return f"{self.api_base.rstrip('/')}{_TOKEN_PATH}"

    def status_url(self, receipt: str) -> str:
        return f"{self.api_base.rstrip('/')}{_STATUS_PATH}/{receipt}"


def config_from_env() -> UscisConfig:
    """Build config from USCIS_* env vars. Blank base ⇒ documented sandbox."""
    base = (os.environ.get("USCIS_API_BASE") or "").strip() or DEFAULT_API_BASE
    return UscisConfig(
        api_base=base,
        client_id=(os.environ.get("USCIS_CLIENT_ID") or "").strip() or None,
        client_secret=(os.environ.get("USCIS_CLIENT_SECRET") or "").strip() or None,
    )


# --------------------------------------------------------------------------- #
# Fixture driver — fictional receipts, NOT stored in the seed
# --------------------------------------------------------------------------- #

# IOE0912345678 is thematically aligned with the seeded Ravi Kumar / Mei Lin
# marriage case (I-130 marriage-based). These live only here; the seed carries
# no receipt number and is not edited.
_FIXTURE: dict[str, dict[str, str]] = {
    "IOE0912345678": {
        "status_title": "Case Was Received",
        "status_detail": (
            "We received your Form I-130, Petition for Alien Relative, and mailed "
            "you a receipt notice describing how we will process your case."
        ),
        "last_updated": "2026-07-18",
    },
    "EAC2590012345": {
        "status_title": "Fingerprint Fee Was Received",
        "status_detail": (
            "We received the biometrics services fee for your case and will schedule "
            "your biometrics appointment. We will mail you the details."
        ),
        "last_updated": "2026-07-10",
    },
    "WAC2190054321": {
        "status_title": "Case Was Approved",
        "status_detail": (
            "We approved your case and mailed you an approval notice. Please allow "
            "up to 30 days for delivery."
        ),
        "last_updated": "2026-06-30",
    },
}


async def _fixture_driver(receipt: str) -> dict[str, Any]:
    row = _FIXTURE.get(receipt)
    if row is None:
        return {"kind": "not_found"}
    return {"kind": "found", "source": "fixture", **row}


# --------------------------------------------------------------------------- #
# Live driver — official USCIS API, OAuth2 client-credentials
# --------------------------------------------------------------------------- #

def _on_pinned_host(url: str, config: UscisConfig) -> bool:
    """True only when url is https and on the exact host derived from api_base.
    The tool never fetches a caller-supplied URL; this re-asserts that every
    request stays on the single allow-listed origin."""
    parsed = urlparse(url)
    return bool(config.host) and parsed.scheme == "https" and parsed.hostname == config.host


async def _fetch_token(client: httpx.AsyncClient, config: UscisConfig) -> str | None:
    url = config.token_url
    if not _on_pinned_host(url, config):
        logger.warning("uscis token url off allow-list host=%s", urlparse(url).hostname)
        return None
    resp = await client.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        logger.warning("uscis token request http=%s", resp.status_code)
        return None
    try:
        token = resp.json().get("access_token")
    except Exception:  # noqa: BLE001
        return None
    return token if isinstance(token, str) and token else None


async def _fetch_status(
    client: httpx.AsyncClient, config: UscisConfig, receipt: str, token: str
) -> dict[str, Any]:
    url = config.status_url(receipt)
    if not _on_pinned_host(url, config):
        return {"kind": "error", "detail": "status url off allow-list"}
    resp = await client.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if resp.status_code == 404:
        return {"kind": "not_found"}
    if resp.status_code == 401:
        # token likely expired (≈30 min) — signal the one allowed retry.
        return {"kind": "error", "detail": "unauthorized", "auth": True}
    if resp.status_code != 200:
        return {"kind": "error", "detail": f"HTTP {resp.status_code}"}
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return {"kind": "error", "detail": "invalid JSON from USCIS API"}
    case_status = body.get("case_status") or {}
    title = case_status.get("current_case_status_text_en")
    if not title:
        # No status text ⇒ do NOT fabricate one; surface a loud error instead.
        return {"kind": "error", "detail": "USCIS response missing status text"}
    return {
        "kind": "found",
        "source": "uscis_api",
        "status_title": title,
        "status_detail": case_status.get("current_case_status_desc_en"),
        "last_updated": case_status.get("modifiedDate"),
    }


async def _live_driver(
    receipt: str, config: UscisConfig, *, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    """OAuth2 client-credentials, then the case-status GET. Returns an outcome
    dict; never raises. One token refresh on 401, no other retries."""
    client_kwargs: dict[str, Any] = {"timeout": _TIMEOUT_S, "follow_redirects": False}
    if transport is not None:
        client_kwargs["transport"] = transport
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            token = await _fetch_token(client, config)
            if token is None:
                return {"kind": "error", "detail": "token request failed"}
            outcome = await _fetch_status(client, config, receipt, token)
            if outcome.get("kind") == "error" and outcome.get("auth"):
                token = await _fetch_token(client, config)
                if token is None:
                    return {"kind": "error", "detail": "token refresh failed"}
                outcome = await _fetch_status(client, config, receipt, token)
            return outcome
    except Exception as exc:  # noqa: BLE001 — loud, never a fabricated status
        logger.warning("uscis live lookup failed err=%s", type(exc).__name__)
        return {"kind": "error", "detail": type(exc).__name__}


# --------------------------------------------------------------------------- #
# Tool assembly
# --------------------------------------------------------------------------- #

def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str() -> genai_types.Schema:
    return genai_types.Schema(type=genai_types.Type.STRING)


_DESCRIPTION = (
    "Look up the LIVE status of a USCIS case by its receipt number (3 letters "
    "then 10 digits, e.g. IOE0912345678). Returns the official USCIS "
    "status_title and status_detail verbatim, plus last_updated and source. "
    'If the result is {"status":"not_found"}, tell the user that receipt is NOT '
    "ON FILE — do not guess and do not retry with a different number. If the "
    'result is {"status":"error"}, say the status service could not be reached. '
    "NEVER state or estimate a USCIS processing time, wait time, or case status "
    "from your own knowledge — report ONLY the status_title and status_detail "
    "this tool returns."
)


def build_uscis_case_status_tool(
    config: UscisConfig | None = None, *, driver: Driver | None = None
) -> ToolSpec:
    """Return the get_uscis_case_status ToolSpec.

    Driver selection: an explicit `driver` wins (used by tests); otherwise the
    live driver when credentials are present, else the offline fixture driver.
    Callers grant this spec to whichever agent needs it — this module wires it
    into no agent's grant list.
    """
    cfg = config or config_from_env()
    if driver is None:
        if cfg.has_creds:
            async def driver(receipt: str) -> dict[str, Any]:  # noqa: E306
                return await _live_driver(receipt, cfg)
        else:
            driver = _fixture_driver

    async def _run(args: dict, ctx: ToolContext) -> str:
        raw = str(args.get("receipt_number", ""))
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "get_uscis_case_status"})

        receipt = normalize_receipt(raw)
        if receipt is None:
            # Reject garbage BEFORE any driver / network call.
            ctx.transcript.log.append("get_uscis_case_status -> invalid receipt rejected")
            return _compact_json(
                {
                    "status": "invalid_receipt",
                    "detail": (
                        "Not a valid USCIS receipt number "
                        "(expected 3 letters followed by 10 digits, e.g. IOE0912345678)."
                    ),
                }
            )

        outcome = await driver(receipt)
        kind = outcome.get("kind")

        if kind == "found":
            ctx.transcript.log.append(
                f"get_uscis_case_status -> {outcome.get('source')} status returned"
            )
            return _compact_json(
                {
                    "receipt_number": receipt,
                    "status_title": outcome.get("status_title"),
                    "status_detail": outcome.get("status_detail"),
                    "last_updated": outcome.get("last_updated"),
                    "source": outcome.get("source"),
                    "fetched_at": _now_iso(),
                }
            )

        if kind == "not_found":
            ctx.transcript.log.append("get_uscis_case_status -> not_found")
            return _compact_json({"receipt_number": receipt, "status": "not_found"})

        # error — loud, never a fabricated status.
        detail = outcome.get("detail", "lookup failed")
        ctx.transcript.log.append(f"get_uscis_case_status -> error: {detail}")
        return _compact_json(
            {"receipt_number": receipt, "status": "error", "detail": detail}
        )

    return ToolSpec(
        name="get_uscis_case_status",
        description=_DESCRIPTION,
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={"receipt_number": _str()},
            required=["receipt_number"],
        ),
        run=_run,
    )
