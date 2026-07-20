"""Offline tests for the auth plane — request → Principal → TenantScope.

Covers both modes: firm mode (Supabase HS256 tokens verified statelessly and
mapped to a provisioned user) and no-account local mode (auto-provisioned
principal, no header). Tokens are minted in-test with the same test secret the
Settings carry — no network, no real Supabase.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.kernel.auth import (
    AuthError,
    Principal,
    get_principal,
    install_auth,
    require_role,
    resolve_principal,
    scope_of,
    verify_token,
)
from app.kernel.config import Settings, get_settings
from app.kernel.store.base import get_matter_store
from app.kernel.store.sqlite_store import SqliteMatterStore

SECRET = "unit-test-jwt-secret-at-least-32-bytes-long"


# --- Fixtures / helpers ----------------------------------------------------
@pytest.fixture
def store(tmp_path: Path) -> SqliteMatterStore:
    return SqliteMatterStore(
        Settings(_env_file=None, matter_store_path=str(tmp_path / "matters.db"))
    )


def firm_settings(tmp_path: Path) -> Settings:
    """Supabase configured → firm auth mode (tokens required)."""
    return Settings(
        _env_file=None,
        supabase_url="https://project.supabase.co",
        supabase_service_key="service-key",
        supabase_jwt_secret=SECRET,
        matter_store_path=str(tmp_path / "matters.db"),
    )


def local_settings(tmp_path: Path) -> Settings:
    """No Supabase → no-account local mode (auth bypassed)."""
    return Settings(
        _env_file=None, matter_store_path=str(tmp_path / "matters.db")
    )


def make_token(
    sub: str,
    *,
    secret: str = SECRET,
    aud: str = "authenticated",
    exp_delta_seconds: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "aud": aud,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=exp_delta_seconds),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# --- scope_of --------------------------------------------------------------
def test_scope_of_maps_principal_to_tenant_scope() -> None:
    scope = scope_of(Principal(user_id="u1", firm_id="f1", role="attorney"))
    assert (scope.firm_id, scope.user_id) == ("f1", "u1")


def test_principal_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    principal = Principal(user_id="u1", firm_id="f1", role="admin")
    with pytest.raises(FrozenInstanceError):
        principal.role = "attorney"  # type: ignore[misc]


# --- verify_token ----------------------------------------------------------
def test_verify_token_valid_returns_claims(tmp_path: Path) -> None:
    claims = verify_token(make_token("auth-123"), firm_settings(tmp_path))
    assert claims["sub"] == "auth-123"
    assert claims["aud"] == "authenticated"


def test_verify_token_expired_rejected(tmp_path: Path) -> None:
    token = make_token("auth-123", exp_delta_seconds=-10)
    with pytest.raises(AuthError):
        verify_token(token, firm_settings(tmp_path))


def test_verify_token_wrong_signature_rejected(tmp_path: Path) -> None:
    token = make_token("auth-123", secret="a-different-secret")
    with pytest.raises(AuthError):
        verify_token(token, firm_settings(tmp_path))


def test_verify_token_wrong_audience_rejected(tmp_path: Path) -> None:
    token = make_token("auth-123", aud="anon")
    with pytest.raises(AuthError):
        verify_token(token, firm_settings(tmp_path))


def test_verify_token_never_echoes_token(tmp_path: Path) -> None:
    token = make_token("auth-123", secret="wrong")
    try:
        verify_token(token, firm_settings(tmp_path))
    except AuthError as exc:
        assert token not in str(exc)
    else:
        pytest.fail("expected AuthError")


def test_verify_token_without_secret_rejected(tmp_path: Path) -> None:
    settings = firm_settings(tmp_path).model_copy(update={"supabase_jwt_secret": None})
    with pytest.raises(AuthError):
        verify_token(make_token("auth-123"), settings)


# --- resolve_principal: firm mode -----------------------------------------
async def test_resolve_principal_valid_token_provisioned_user(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    settings = firm_settings(tmp_path)
    firm = await store.create_firm("Alpha LLP")
    user = await store.create_user(firm.id, "a@alpha.test", "attorney", "auth-abc")

    principal = await resolve_principal(
        f"Bearer {make_token('auth-abc')}", settings, store
    )
    assert principal.user_id == user.id
    assert principal.firm_id == firm.id
    assert principal.role == "attorney"


async def test_resolve_principal_unprovisioned_sub_rejected(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    settings = firm_settings(tmp_path)
    with pytest.raises(AuthError) as excinfo:
        await resolve_principal(
            f"Bearer {make_token('auth-nobody')}", settings, store
        )
    assert "provisioned" in str(excinfo.value)


async def test_resolve_principal_missing_header_rejected(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    with pytest.raises(AuthError):
        await resolve_principal(None, firm_settings(tmp_path), store)


async def test_resolve_principal_malformed_header_rejected(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    with pytest.raises(AuthError):
        await resolve_principal("Token xyz", firm_settings(tmp_path), store)


# --- resolve_principal: no-account local fallback --------------------------
async def test_local_fallback_returns_principal_without_header(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    principal = await resolve_principal(None, local_settings(tmp_path), store)
    assert principal.role == "attorney"
    assert principal.user_id and principal.firm_id


async def test_local_fallback_is_idempotent(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    settings = local_settings(tmp_path)
    first = await resolve_principal(None, settings, store)
    second = await resolve_principal(None, settings, store)
    assert first == second  # same firm + user across calls, no duplicate firm


async def test_local_fallback_ignores_any_header(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    # Even a well-formed-looking header is ignored in local mode.
    principal = await resolve_principal(
        "Bearer whatever", local_settings(tmp_path), store
    )
    assert principal.role == "attorney"


async def test_local_scope_round_trips_through_store(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    principal = await resolve_principal(None, local_settings(tmp_path), store)
    scope = scope_of(principal)
    matter = await store.create_matter(scope, "o1a", "Test Matter")
    listed = await store.list_matters(scope)
    assert [m.id for m in listed] == [matter.id]
    assert matter.created_by == principal.user_id
    assert matter.firm_id == principal.firm_id


async def test_local_fallback_when_secret_unset_despite_supabase(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    # Supabase storage configured but JWT secret missing → still local mode.
    settings = firm_settings(tmp_path).model_copy(
        update={"supabase_jwt_secret": None}
    )
    principal = await resolve_principal(None, settings, store)
    assert principal.role == "attorney"


# --- FastAPI wiring: get_principal, require_role, error handler ------------
def _build_app(settings: Settings, store: SqliteMatterStore) -> FastAPI:
    app = FastAPI()
    install_auth(app)

    @app.get("/me")
    async def me(principal: Principal = Depends(get_principal)) -> dict:
        return {"role": principal.role, "firm_id": principal.firm_id}

    @app.get("/admin-only")
    async def admin_only(
        principal: Principal = Depends(require_role("admin")),
    ) -> dict:
        return {"role": principal.role}

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_matter_store] = lambda: store
    return app


async def test_get_principal_endpoint_valid_token(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    settings = firm_settings(tmp_path)
    firm = await store.create_firm("Alpha LLP")
    await store.create_user(firm.id, "admin@alpha.test", "admin", "auth-admin")

    client = TestClient(_build_app(settings, store))
    resp = client.get("/me", headers={"Authorization": f"Bearer {make_token('auth-admin')}"})
    assert resp.status_code == 200
    assert resp.json() == {"role": "admin", "firm_id": firm.id}


def test_auth_error_maps_to_401_envelope(tmp_path: Path, store: SqliteMatterStore) -> None:
    client = TestClient(_build_app(firm_settings(tmp_path), store))
    token = make_token("auth-x", exp_delta_seconds=-10)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]
    assert token not in body["error"]  # never echoes the token


def test_missing_header_firm_mode_401(tmp_path: Path, store: SqliteMatterStore) -> None:
    client = TestClient(_build_app(firm_settings(tmp_path), store))
    resp = client.get("/me")
    assert resp.status_code == 401
    assert resp.json()["success"] is False


async def test_require_role_allows_matching_role(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    settings = firm_settings(tmp_path)
    firm = await store.create_firm("Alpha LLP")
    await store.create_user(firm.id, "admin@alpha.test", "admin", "auth-admin")

    client = TestClient(_build_app(settings, store))
    resp = client.get(
        "/admin-only", headers={"Authorization": f"Bearer {make_token('auth-admin')}"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_require_role_denies_other_role(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    settings = firm_settings(tmp_path)
    firm = await store.create_firm("Alpha LLP")
    await store.create_user(firm.id, "staff@alpha.test", "staff", "auth-staff")

    client = TestClient(_build_app(settings, store))
    resp = client.get(
        "/admin-only", headers={"Authorization": f"Bearer {make_token('auth-staff')}"}
    )
    assert resp.status_code == 401
    assert resp.json()["success"] is False


def test_local_mode_endpoint_needs_no_header(
    tmp_path: Path, store: SqliteMatterStore
) -> None:
    client = TestClient(_build_app(local_settings(tmp_path), store))
    resp = client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "attorney"
