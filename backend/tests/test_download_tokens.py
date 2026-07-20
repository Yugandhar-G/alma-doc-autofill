"""Scoped artifact-download token seam.

Two layers:
- the mint/verify crypto (pure functions in app.kernel.auth), and
- the GET /api/population-artifact/{id} route honoring ?t=, plus the
  POST .../link mint endpoint.

The route reads settings via the module-level get_settings(), so we monkeypatch
app.main.get_settings for the HTTP tests (dependency_overrides only reaches
Depends()). stored_artifact_path is faked to a tmp file so no real population
run is needed.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.kernel.auth import (
    DownloadTokenResult,
    Principal,
    get_principal,
    mint_download_token,
    verify_download_token,
)
from app.kernel.config import Settings, get_settings as get_kernel_settings

SECRET = "download-token-secret-at-least-32-bytes-long!!"
ARTIFACT_ID = "b" * 64
OTHER_ID = "c" * 64


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, download_token_secret=SECRET, **overrides)


# --- Crypto contract (pure) ------------------------------------------------
def test_mint_then_verify_round_trips() -> None:
    settings = _settings()
    token = mint_download_token(ARTIFACT_ID, settings)
    assert token is not None
    assert verify_download_token(ARTIFACT_ID, token, settings) is DownloadTokenResult.VALID


def test_expired_token_is_invalid() -> None:
    settings = _settings(download_token_ttl_seconds=100)
    token = mint_download_token(ARTIFACT_ID, settings, now=1_000)
    # Verify well past expiry (1_000 + 100).
    assert (
        verify_download_token(ARTIFACT_ID, token, settings, now=2_000)
        is DownloadTokenResult.INVALID
    )


def test_forged_signature_is_invalid() -> None:
    settings = _settings()
    token = mint_download_token(ARTIFACT_ID, settings)
    expiry, _, _sig = token.partition(".")
    forged = f"{expiry}.{'0' * 64}"
    assert verify_download_token(ARTIFACT_ID, forged, settings) is DownloadTokenResult.INVALID


def test_token_for_other_id_is_invalid() -> None:
    settings = _settings()
    token = mint_download_token(ARTIFACT_ID, settings)
    # A token minted for ARTIFACT_ID must not authorize OTHER_ID.
    assert verify_download_token(OTHER_ID, token, settings) is DownloadTokenResult.INVALID


def test_malformed_token_is_invalid() -> None:
    settings = _settings()
    for bad in ("", "no-separator", "notanumber.deadbeef", "123."):
        assert verify_download_token(ARTIFACT_ID, bad, settings) is DownloadTokenResult.INVALID


def test_no_secret_is_not_configured() -> None:
    settings = Settings(_env_file=None)  # no download secret, no jwt secret
    assert mint_download_token(ARTIFACT_ID, settings) is None
    assert (
        verify_download_token(ARTIFACT_ID, "anything", settings)
        is DownloadTokenResult.NOT_CONFIGURED
    )


def test_secret_falls_back_to_supabase_jwt_secret() -> None:
    settings = Settings(_env_file=None, supabase_jwt_secret=SECRET)
    token = mint_download_token(ARTIFACT_ID, settings)
    assert token is not None
    assert verify_download_token(ARTIFACT_ID, token, settings) is DownloadTokenResult.VALID


# --- GET route honors ?t= --------------------------------------------------
@pytest.fixture
def artifact_file(tmp_path: Path):
    path = tmp_path / (ARTIFACT_ID + ".a28.pdf")
    path.write_bytes(b"%PDF-1.4 fake artifact")
    return path


def _wire_get(monkeypatch, artifact_file, settings: Settings) -> TestClient:
    monkeypatch.setattr(m, "get_settings", lambda: settings)
    monkeypatch.setattr(m, "stored_artifact_path", lambda _id: artifact_file)
    return TestClient(m.app)


def test_route_valid_token_serves(monkeypatch, artifact_file) -> None:
    settings = _settings()
    client = _wire_get(monkeypatch, artifact_file, settings)
    token = mint_download_token(ARTIFACT_ID, settings)
    resp = client.get(f"/api/population-artifact/{ARTIFACT_ID}?t={token}")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_route_forged_token_403(monkeypatch, artifact_file) -> None:
    settings = _settings()
    client = _wire_get(monkeypatch, artifact_file, settings)
    resp = client.get(f"/api/population-artifact/{ARTIFACT_ID}?t=123.{'0' * 64}")
    assert resp.status_code == 403
    assert resp.json()["success"] is False


def test_route_other_id_token_403(monkeypatch, artifact_file) -> None:
    settings = _settings()
    client = _wire_get(monkeypatch, artifact_file, settings)
    token = mint_download_token(OTHER_ID, settings)  # minted for a different id
    resp = client.get(f"/api/population-artifact/{ARTIFACT_ID}?t={token}")
    assert resp.status_code == 403


def test_route_no_token_still_serves_in_dev(monkeypatch, artifact_file) -> None:
    # No signing secret configured (pure-local dev) → the route needs no token.
    settings = Settings(_env_file=None)
    client = _wire_get(monkeypatch, artifact_file, settings)
    resp = client.get(f"/api/population-artifact/{ARTIFACT_ID}")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_route_no_token_serves_when_secret_set(monkeypatch, artifact_file) -> None:
    # A programmatic caller (bearer already authorized by the sidecar) hits the
    # route with no ?t= — it still serves; the query token is only for browser
    # downloads that cannot set a header.
    settings = _settings()
    client = _wire_get(monkeypatch, artifact_file, settings)
    resp = client.get(f"/api/population-artifact/{ARTIFACT_ID}")
    assert resp.status_code == 200


# --- POST .../link mint endpoint -------------------------------------------
def test_link_endpoint_mints_verifiable_url(monkeypatch, artifact_file) -> None:
    settings = _settings()
    monkeypatch.setattr(m, "stored_artifact_path", lambda _id: artifact_file)
    m.app.dependency_overrides[get_kernel_settings] = lambda: settings
    m.app.dependency_overrides[get_principal] = lambda: Principal(
        user_id="u1", firm_id="f1", role="attorney"
    )
    try:
        client = TestClient(m.app)
        body = client.post(f"/api/population-artifact/{ARTIFACT_ID}/link").json()
        assert body["success"] is True
        url = body["data"]["url"]
        assert f"/api/population-artifact/{ARTIFACT_ID}" in url
        assert "t=" in url
        token = url.split("t=", 1)[1]
        assert verify_download_token(ARTIFACT_ID, token, settings) is DownloadTokenResult.VALID
    finally:
        m.app.dependency_overrides.clear()


def test_link_endpoint_unknown_artifact(monkeypatch) -> None:
    settings = _settings()
    monkeypatch.setattr(m, "stored_artifact_path", lambda _id: None)
    m.app.dependency_overrides[get_kernel_settings] = lambda: settings
    m.app.dependency_overrides[get_principal] = lambda: Principal(
        user_id="u1", firm_id="f1", role="attorney"
    )
    try:
        client = TestClient(m.app)
        body = client.post(f"/api/population-artifact/{ARTIFACT_ID}/link").json()
        assert body["success"] is False
    finally:
        m.app.dependency_overrides.clear()
