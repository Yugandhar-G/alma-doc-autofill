"""Staff-auth route tests.

The ``client`` fixture (conftest) forces demo mode by clearing
YUNAKI_STAFF_PASSWORD; each test here that exercises the guarded path re-sets
the password via monkeypatch. auth reads the env per-request, so setting it
after the app is built is intentional and sufficient.
"""
from __future__ import annotations

import time

from intake_workflow.domain import api
from intake_workflow.web import auth
from intake_workflow.web.auth import COOKIE_NAME

PASSWORD = "open-sesame"


def _radar_empty(monkeypatch):
    """Dashboard calls the domain radar; stub it so a 200 render doesn't depend
    on real domain behavior."""
    monkeypatch.setattr(api, "i751_radar", lambda store, now=None: [])


# --------------------------------------------------------------------- demo mode

def test_demo_mode_allows_staff(client, monkeypatch):
    _radar_empty(monkeypatch)
    r = client.get("/staff")
    assert r.status_code == 200


# ------------------------------------------------------------- guarding + login

def test_password_set_redirects_unauthenticated_to_login(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    r = client.get("/staff", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/staff-login"


def test_login_page_renders(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    r = client.get("/staff-login")
    assert r.status_code == 200
    assert "Staff sign-in" in r.text
    assert 'type="password"' in r.text


def test_correct_password_sets_cookie_and_allows(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    _radar_empty(monkeypatch)

    r = client.post("/staff-login", data={"password": PASSWORD}, follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/staff"
    assert r.cookies.get(COOKIE_NAME)  # a session cookie was issued
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    # The issued cookie is now on the client jar -> the guarded route opens.
    assert client.get("/staff").status_code == 200


def test_wrong_password_errors_and_sets_no_cookie(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)

    r = client.post("/staff-login", data={"password": "wrong"}, follow_redirects=False)

    assert r.status_code == 401
    assert "not correct" in r.text
    assert r.cookies.get(COOKIE_NAME) is None
    # Still locked out.
    r2 = client.get("/staff", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == "/staff-login"


# --------------------------------------------------------------- bad cookies

def test_tampered_cookie_is_rejected(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    # Far-future expiry but a signature that was never produced by our key.
    client.cookies.set(COOKIE_NAME, "9999999999.deadbeefdeadbeef")
    r = client.get("/staff", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/staff-login"


def test_expired_cookie_is_rejected(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    # Correctly signed, but the expiry is in the past.
    key = auth._signing_key(PASSWORD)
    past = int(time.time()) - 10
    client.cookies.set(COOKIE_NAME, f"{past}.{auth._sign(past, key)}")
    r = client.get("/staff", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/staff-login"


# --------------------------------------------------------------------- logout

def test_logout_clears_session(client, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    _radar_empty(monkeypatch)

    client.post("/staff-login", data={"password": PASSWORD}, follow_redirects=False)
    assert client.get("/staff").status_code == 200

    r = client.post("/staff-logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/staff-login"

    # The session is gone; the guard kicks back in.
    r2 = client.get("/staff", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == "/staff-login"


def test_logout_button_shown_only_when_authenticated(client, monkeypatch):
    _radar_empty(monkeypatch)

    # Demo mode: no password configured -> no logout affordance.
    assert "/staff-logout" not in client.get("/staff").text

    # Password + valid session -> the nav shows the sign-out button.
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    client.post("/staff-login", data={"password": PASSWORD}, follow_redirects=False)
    assert "/staff-logout" in client.get("/staff").text


# --------------------------------------------------- client portal stays open

def test_client_portal_is_never_guarded(client, make_case, make_progress, monkeypatch):
    monkeypatch.setenv("YUNAKI_STAFF_PASSWORD", PASSWORD)
    case = make_case()
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    # No staff session at all, yet the magic-link portal resolves normally.
    r = client.get("/c/petitok")
    assert r.status_code == 200
    assert "Ada" in r.text
