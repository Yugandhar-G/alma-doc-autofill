"""Authentication + the tenancy principal — how an HTTP request becomes a
TenantScope.

Two modes, mirroring the storage-fallback philosophy in CLAUDE.md:

- **Firm mode (Supabase Auth):** the desktop app signs in to the firm via
  Supabase GoTrue, which issues an HS256 access token signed with the project
  JWT secret. FastAPI verifies that token statelessly (signature + exp + aud),
  maps its `sub` (the auth-provider subject) to a provisioned User, and derives
  the Principal from that row. No session store, no round-trip to Supabase on
  each request.

- **No-account / local mode:** when Supabase is not configured (or the JWT
  secret is unset), there is zero auth setup — no header required. A single
  deterministic local firm + attorney user is auto-provisioned idempotently on
  first use and every request runs as that principal. The well-known link is
  the `auth_provider_id` "local-dev"; the store still mints the actual ids.

The Principal is the only thing endpoints see; `scope_of` turns it into the
TenantScope the matter store filters every read/write by. A request literally
cannot express a firm it was not resolved into.

Security: tokens are never logged or echoed. Every rejection raises a single
`AuthError` whose message is a fixed, generic string — it never contains the
token, the claims, or which check failed in a way that leaks the credential.
"""
import asyncio
import hashlib
import hmac
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.kernel.config import Settings, get_settings
from app.kernel.store.base import MatterStore, TenantScope, get_matter_store
from app.kernel.store.models import UserRole
from app.schemas import ApiResponse

logger = logging.getLogger("yunaki.kernel.auth")

# GoTrue signs access tokens with this audience; we accept nothing else.
_ACCEPTED_AUDIENCE = "authenticated"

# No-account mode well-known identity. The auth_provider_id is the fixed link;
# the store mints the firm/user ids on first provision.
_LOCAL_AUTH_ID = "local-dev"
_LOCAL_FIRM_NAME = "Local Firm"
_LOCAL_USER_EMAIL = "local@yunaki.local"
_LOCAL_USER_ROLE: UserRole = "attorney"

# Serializes concurrent first-callers so the local firm/user is provisioned
# exactly once (look-up-before-create is the idempotency guarantee; the lock
# just closes the create-create race). Process-wide by design — the local firm
# is a singleton.
_local_lock = asyncio.Lock()


class AuthError(Exception):
    """Any authentication/authorization failure. One type, mapped to 401 by
    install_auth. The message is a fixed generic string and MUST NOT carry the
    token, the raw claims, or the specific failing check."""


@dataclass(frozen=True)
class Principal:
    """The resolved acting identity for a request. Frozen so it cannot be
    mutated mid-request to widen access."""

    user_id: str
    firm_id: str
    role: UserRole


def scope_of(principal: Principal) -> TenantScope:
    """Turn a Principal into the TenantScope the matter store filters by."""
    return TenantScope(firm_id=principal.firm_id, user_id=principal.user_id)


def verify_token(token: str, settings: Settings) -> dict:
    """Verify a GoTrue HS256 access token: signature (project JWT secret),
    expiry, and audience == "authenticated". Returns the decoded claims.

    Raises AuthError (generic message) on any failure. The token is never
    included in the raised message or in logs."""
    secret = settings.supabase_jwt_secret
    if not secret:
        # Structural misconfiguration, not a bad credential — but still generic.
        raise AuthError("authentication is not configured")
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_ACCEPTED_AUDIENCE,
        )
    except jwt.PyJWTError:
        # Covers bad signature, expiry, wrong/missing aud, malformed token.
        # Deliberately does not chain the token or the underlying reason.
        raise AuthError("invalid or expired token")


def _bearer_token(authorization: str | None) -> str:
    """Extract the bearer token from an Authorization header value."""
    if not authorization:
        raise AuthError("missing authorization header")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential.strip():
        raise AuthError("malformed authorization header")
    return credential.strip()


async def _local_principal(store: MatterStore) -> Principal:
    """Resolve (auto-provisioning once) the no-account local principal."""
    async with _local_lock:
        user = await store.get_user_by_auth_id(_LOCAL_AUTH_ID)
        if user is None:
            firm = await store.create_firm(_LOCAL_FIRM_NAME)
            user = await store.create_user(
                firm.id, _LOCAL_USER_EMAIL, _LOCAL_USER_ROLE, _LOCAL_AUTH_ID
            )
            logger.info("provisioned local firm firm_id=%s user_id=%s", firm.id, user.id)
    return Principal(user_id=user.id, firm_id=user.firm_id, role=user.role)


async def resolve_principal(
    authorization: str | None, settings: Settings, store: MatterStore
) -> Principal:
    """Core request-to-Principal logic (header-string in, Principal out) —
    the testable seam under the FastAPI dependency.

    Dev/no-account fallback: when Supabase is not enabled OR the JWT secret is
    unset, ignore any header and return the local principal. Otherwise require a
    verified bearer token whose `sub` maps to a provisioned firm member."""
    if not settings.supabase_enabled or not settings.supabase_jwt_secret:
        return await _local_principal(store)

    token = _bearer_token(authorization)
    claims = verify_token(token, settings)
    sub = claims.get("sub")
    if not sub:
        raise AuthError("invalid token claims")
    user = await store.get_user_by_auth_id(sub)
    if user is None:
        # Known-good token, but no firm member linked to this subject.
        raise AuthError("user not provisioned")
    return Principal(user_id=user.id, firm_id=user.firm_id, role=user.role)


async def get_principal(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: MatterStore = Depends(get_matter_store),
) -> Principal:
    """FastAPI dependency: resolve the acting Principal for the request.

    settings and store come through DI so tests override them via
    app.dependency_overrides on get_settings / get_matter_store; the header is
    read off the raw request. All logic lives in resolve_principal."""
    return await resolve_principal(
        request.headers.get("Authorization"), settings, store
    )


def require_role(
    *roles: UserRole,
) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    """Dependency factory gating an endpoint to one or more roles (e.g. admin).
    Denials raise AuthError → 401, same envelope as an auth failure."""
    allowed = frozenset(roles)

    async def _dependency(
        principal: Principal = Depends(get_principal),
    ) -> Principal:
        if principal.role not in allowed:
            raise AuthError("insufficient role")
        return principal

    return _dependency


# --- Scoped artifact-download tokens ---------------------------------------
# A single-purpose allowance for browser-initiated downloads: the artifact-GET
# route (GET /api/population-artifact/{id}) is reachable from an <a href> that
# carries no Authorization header, so it also accepts a short-lived signed token
# as ?t=. The token is an HMAC over (artifact_id, expiry) — it authorizes ONE
# artifact id for a few minutes, nothing else. Programmatic callers keep using
# the bearer path; this never widens their access.
_TOKEN_SEP = "."


class DownloadTokenResult(Enum):
    """Outcome of verifying a ?t= artifact-download token."""

    VALID = "valid"
    INVALID = "invalid"  # forged, expired, wrong id, or malformed
    NOT_CONFIGURED = "not_configured"  # no signing secret (pure-local dev)


def _download_secret(settings: Settings) -> str | None:
    """Signing secret for download tokens: the dedicated setting, else the
    Supabase JWT secret (same trust root as request auth). None in pure-local
    dev, where the route needs no token to begin with."""
    return settings.download_token_secret or settings.supabase_jwt_secret


def _sign_download(artifact_id: str, expiry: int, secret: str) -> str:
    message = f"{artifact_id}{_TOKEN_SEP}{expiry}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def mint_download_token(
    artifact_id: str, settings: Settings, now: int | None = None
) -> str | None:
    """Mint a short-lived token authorizing a download of exactly this
    artifact id. Returns None when no signing secret is configured (dev mode —
    the route serves without a token there)."""
    secret = _download_secret(settings)
    if not secret:
        return None
    expiry = (now or int(time.time())) + settings.download_token_ttl_seconds
    signature = _sign_download(artifact_id, expiry, secret)
    return f"{expiry}{_TOKEN_SEP}{signature}"


def verify_download_token(
    artifact_id: str, token: str, settings: Settings, now: int | None = None
) -> DownloadTokenResult:
    """Verify a ?t= token against an artifact id. Constant-time signature
    compare; rejects expiry, wrong id, and malformed tokens the same way (no
    oracle). NOT_CONFIGURED when there is no secret (dev)."""
    secret = _download_secret(settings)
    if not secret:
        return DownloadTokenResult.NOT_CONFIGURED
    expiry_raw, _, signature = token.partition(_TOKEN_SEP)
    if not signature:
        return DownloadTokenResult.INVALID
    try:
        expiry = int(expiry_raw)
    except ValueError:
        return DownloadTokenResult.INVALID
    if (now or int(time.time())) >= expiry:
        return DownloadTokenResult.INVALID
    expected = _sign_download(artifact_id, expiry, secret)
    if not hmac.compare_digest(signature, expected):
        return DownloadTokenResult.INVALID
    return DownloadTokenResult.VALID


def install_auth(app: FastAPI) -> None:
    """Register the AuthError → 401 handler on the app, in the standard
    ApiResponse envelope. The generic AuthError message is safe to surface (it
    never contains the token or the specific failing check)."""

    @app.exception_handler(AuthError)
    async def _auth_error_handler(_: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=ApiResponse(success=False, error=str(exc)).model_dump(),
        )
