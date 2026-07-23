"""Staff authentication. CONTRACT (phase 2): implemented by the auth agent.

- ``require_staff`` is a FastAPI dependency guarding every /staff route
  (wired as a router dependency in routes_staff.py). Demo mode: when
  YUNAKI_STAFF_PASSWORD is unset, it must allow all requests so local
  demos keep working.
- ``auth_router`` serves GET/POST /staff-login and POST /staff-logout
  (included by app/main.py).
- Session: signed HttpOnly cookie (SameSite=Lax); signing secret from
  YUNAKI_SECRET, else derived from the password; password check uses a
  constant-time comparison.

Implementation notes (stdlib only, no new deps):
  cookie value = ``<expiry-unix-ts>.<hmac-sha256-hex>`` where the HMAC is
  taken over the expiry string with the signing key. Tampered or expired
  cookies fail validation and are treated as unauthenticated. Sessions live
  for ``SESSION_TTL`` seconds (12 hours).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from intake_workflow.web.templating import templates

auth_router = APIRouter()

COOKIE_NAME = "yunaki_staff"
SESSION_TTL = 12 * 60 * 60  # 12 hours, in seconds
LOGIN_PATH = "/staff-login"


# --------------------------------------------------------------------- config

def _configured_password() -> str | None:
    """The staff password, or ``None`` in demo mode (unset/empty)."""
    password = os.environ.get("YUNAKI_STAFF_PASSWORD")
    return password or None


def _signing_key(password: str) -> bytes:
    """HMAC key: YUNAKI_SECRET when set, else derived from the password so a
    zero-config demo still gets a stable, password-bound key."""
    secret = os.environ.get("YUNAKI_SECRET")
    if secret:
        return secret.encode("utf-8")
    return hashlib.sha256(("yunaki-session:" + password).encode("utf-8")).digest()


# --------------------------------------------------------------------- cookie

def _sign(expiry: int, key: bytes) -> str:
    return hmac.new(key, str(expiry).encode("ascii"), hashlib.sha256).hexdigest()


def _make_cookie_value(key: bytes) -> str:
    expiry = int(time.time()) + SESSION_TTL
    return f"{expiry}.{_sign(expiry, key)}"


def _cookie_is_valid(value: str | None, key: bytes) -> bool:
    """True only for an untampered, unexpired cookie signed with ``key``."""
    if not value or "." not in value:
        return False
    expiry_str, _, signature = value.partition(".")
    try:
        expiry = int(expiry_str)
    except ValueError:
        return False
    expected = _sign(expiry, key)
    if not hmac.compare_digest(signature, expected):
        return False
    return expiry > int(time.time())


def _is_authenticated(request: Request) -> bool:
    """Demo mode (no password) is always authenticated; otherwise a valid
    session cookie is required."""
    password = _configured_password()
    if not password:
        return True
    return _cookie_is_valid(request.cookies.get(COOKIE_NAME), _signing_key(password))


# ----------------------------------------------------------------- dependency

def require_staff(request: Request) -> None:
    """FastAPI dependency guarding every /staff route. Passes through in demo
    mode; otherwise redirects unauthenticated requests to the login page."""
    if _is_authenticated(request):
        return None
    raise HTTPException(status_code=303, headers={"Location": LOGIN_PATH})


# --------------------------------------------------------------------- routes

@auth_router.get(LOGIN_PATH)
def login_form(request: Request):
    return templates.TemplateResponse(request, "staff/login.html", {"error": None})


@auth_router.post(LOGIN_PATH)
def login_submit(request: Request, password: str = Form("")):
    configured = _configured_password()
    if not configured:
        # Demo mode: nothing to authenticate against — just go to the dashboard.
        return RedirectResponse("/staff", status_code=303)
    if hmac.compare_digest(password.encode("utf-8"), configured.encode("utf-8")):
        value = _make_cookie_value(_signing_key(configured))
        response = RedirectResponse("/staff", status_code=303)
        response.set_cookie(
            COOKIE_NAME, value,
            max_age=SESSION_TTL, httponly=True, samesite="lax", path="/",
        )
        return response
    return templates.TemplateResponse(
        request,
        "staff/login.html",
        {"error": "That password is not correct. Please try again."},
        status_code=401,
    )


@auth_router.post("/staff-logout")
def logout():
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def _staff_logout_available(request: Request) -> bool:
    """Template helper: show the nav logout button only when a password is
    configured AND this request carries a valid session. False in demo mode
    and for unauthenticated renders, so base.html stays safe everywhere."""
    return bool(_configured_password()) and _is_authenticated(request)


# Registered on the shared Jinja env (templating.py owns the instance; this is
# an additive global, not an edit to that frozen module) so base.html can ask
# whether to render the logout button.
templates.env.globals["staff_logout_available"] = _staff_logout_available
