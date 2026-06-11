"""Refresh token issuance, rotation, and HTTP routes."""

from __future__ import annotations

import time

import pytest

from plugins.app_gateway.auth import JwtError, verify_hs256_jwt
from plugins.app_gateway.auth_tokens import (
    AuthTokenService,
    RefreshTokenError,
    RefreshTokenStore,
    access_ttl_seconds,
)
from plugins.app_gateway.config import AppGatewayConfig
from tests.plugins.app_gateway_dev_helpers import seed_dev_sms_otp

SECRET = "test-secret-key"


@pytest.fixture
def auth_config():
    return AppGatewayConfig(
        jwt_secret=SECRET,
        refresh_tokens_enabled=True,
        jwt_access_ttl_minutes=60,
        jwt_refresh_ttl_days=7,
    )


def test_access_token_has_typ_access(auth_config):
    svc = AuthTokenService(auth_config)
    pair = svc.issue_login_tokens(
        user_id="u_test",
        phone="8613800138000",
        session_id="app",
        device_id="iphone",
    )
    claims = verify_hs256_jwt(pair.access_token, SECRET)
    assert claims["typ"] == "access"
    assert claims["sub"] == "u_test"
    assert pair.refresh_token
    assert pair.expires_in == access_ttl_seconds(auth_config)
    assert pair.refresh_expires_in == 7 * 86400


def test_refresh_rotates_token(auth_config):
    svc = AuthTokenService(auth_config)
    first = svc.issue_login_tokens(
        user_id="u_test",
        phone="8613800138000",
        session_id="app",
    )
    old_refresh = first.refresh_token
    assert old_refresh

    second = svc.refresh_tokens(old_refresh)
    assert second.access_token
    assert second.refresh_token
    assert second.refresh_token != old_refresh

    with pytest.raises(RefreshTokenError):
        svc.refresh_tokens(old_refresh)


def test_refresh_rejects_empty(auth_config):
    svc = AuthTokenService(auth_config)
    with pytest.raises(RefreshTokenError, match="required"):
        svc.refresh_tokens("")


def test_refresh_disabled_uses_long_access_only():
    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        refresh_tokens_enabled=False,
        jwt_ttl_hours=24,
    )
    svc = AuthTokenService(cfg)
    pair = svc.issue_login_tokens(
        user_id="u_test",
        phone="8613800138000",
    )
    assert pair.refresh_token is None
    assert pair.expires_in == 24 * 3600


def test_refresh_store_revoke(auth_config):
    store = RefreshTokenStore(auth_config)
    token = store.create(
        user_id="u_test",
        phone="8613800138000",
        session_id="app",
        device_id=None,
    )
    record = store.consume(token)
    assert record["user_id"] == "u_test"

    token2 = store.create(
        user_id="u_test",
        phone="8613800138000",
        session_id="app",
        device_id=None,
    )
    store.revoke(token2)
    with pytest.raises(RefreshTokenError):
        store.consume(token2)


def test_login_and_refresh_http(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    from fastapi.testclient import TestClient

    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        auth_mode="dev",
        dev_sms_code="111111",
        refresh_tokens_enabled=True,
        jwt_access_ttl_minutes=30,
        require_jwt=True,
    )
    app = create_app(cfg)
    client = TestClient(app)

    seed_dev_sms_otp("13800138000")

    login = client.post(
        "/v1/auth/login",
        json={"phone": "13800138000", "code": "111111", "device_id": "test"},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 30 * 60

    claims = verify_hs256_jwt(body["access_token"], SECRET)
    assert claims["typ"] == "access"

    refresh = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"]
    assert refreshed["refresh_token"] != body["refresh_token"]

    stale = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )
    assert stale.status_code == 403

    logout = client.post(
        "/v1/auth/logout",
        json={"refresh_token": refreshed["refresh_token"]},
    )
    assert logout.status_code == 200
    assert logout.json()["ok"] is True

    again = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": refreshed["refresh_token"]},
    )
    assert again.status_code in (401, 403)


def test_access_token_rejects_refresh_typ_in_user_routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))

    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(jwt_secret=SECRET, require_jwt=True)
    app = create_app(cfg)
    client = TestClient(app)

    bad = encode_hs256_jwt(
        {
            "sub": "u_test",
            "typ": "refresh",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
    )
    resp = client.get(
        "/v1/onboarding/status",
        headers={"X-User-Token": bad},
    )
    assert resp.status_code == 401
