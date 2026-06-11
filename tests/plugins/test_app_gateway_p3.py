"""P3: HttpOnly cookie auth, upload retention, delete SMS verification."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.data_retention import purge_stale_uploads, run_data_retention
from tests.plugins.app_gateway_dev_helpers import seed_dev_sms_otp

SECRET = "test-secret-key"


@pytest.fixture
def gateway_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_login_sets_httponly_cookies(gateway_home):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        auth_mode="dev",
        dev_sms_code="111111",
        refresh_tokens_enabled=True,
        require_jwt=True,
        web_cookie_auth=True,
    )
    app = create_app(cfg)
    client = TestClient(app)

    seed_dev_sms_otp("13800138000")

    login = client.post(
        "/v1/auth/login",
        json={"phone": "13800138000", "code": "111111", "device_id": "web"},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    assert login.status_code == 200
    assert login.cookies.get("hermes_access")
    assert login.cookies.get("hermes_refresh")

    status = client.get("/v1/onboarding/status")
    assert status.status_code == 200


def test_refresh_from_cookie_without_body(gateway_home):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        auth_mode="dev",
        dev_sms_code="111111",
        refresh_tokens_enabled=True,
        require_jwt=True,
        web_cookie_auth=True,
    )
    app = create_app(cfg)
    client = TestClient(app)

    seed_dev_sms_otp("13800138000")

    login = client.post(
        "/v1/auth/login",
        json={"phone": "13800138000", "code": "111111"},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    assert login.status_code == 200

    refresh = client.post(
        "/v1/auth/refresh",
        json={},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]
    assert refresh.cookies.get("hermes_access")


def test_logout_clears_auth_cookies(gateway_home):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        auth_mode="dev",
        dev_sms_code="111111",
        refresh_tokens_enabled=True,
        web_cookie_auth=True,
    )
    app = create_app(cfg)
    client = TestClient(app)

    seed_dev_sms_otp("13800138000")

    client.post(
        "/v1/auth/login",
        json={"phone": "13800138000", "code": "111111"},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    logout = client.post(
        "/v1/auth/logout",
        json={},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    assert logout.status_code == 200
    set_cookie = logout.headers.get("set-cookie") or ""
    assert "hermes_access=" in set_cookie or logout.cookies.get("hermes_access") == ""


def test_delete_me_requires_sms_code(gateway_home):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        require_jwt=True,
        delete_account_sms_verify=True,
        auth_mode="dev",
        dev_sms_code="111111",
    )
    with patch("plugins.app_gateway.redis_policy.validate_app_gateway_redis"):
        app = create_app(cfg, vector_memory=MagicMock(enabled=False))
    client = TestClient(app)

    token = encode_hs256_jwt(
        {
            "sub": "u_delete_sms",
            "typ": "access",
            "session_id": "app",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
    )
    headers = {"X-User-Token": token}

    missing = client.request(
        "DELETE",
        "/v1/me",
        headers=headers,
        json={"confirm": True},
    )
    assert missing.status_code == 400

    with patch(
        "plugins.app_gateway.account_compliance.verify_delete_account_code",
    ) as verify_mock, patch(
        "plugins.app_gateway.account_compliance.delete_user_account",
        return_value={"ok": True, "user_id": "u_delete_sms"},
    ):
        ok = client.request(
            "DELETE",
            "/v1/me",
            headers=headers,
            json={"confirm": True, "code": "111111"},
        )
    assert ok.status_code == 200
    verify_mock.assert_called_once()


def test_verify_delete_account_code_dev_mode(gateway_home):
    from plugins.app_gateway.account_compliance import verify_delete_account_code
    from plugins.app_gateway.user_registry import get_user_registry

    cfg = AppGatewayConfig(auth_mode="dev", dev_sms_code="111111")
    registry = get_user_registry()
    record = registry.upsert_user("u_test_verify", "8613800138000")
    seed_dev_sms_otp("8613800138000")

    verify_delete_account_code(record.user_id, "111111", cfg)


def test_purge_stale_uploads_local(gateway_home, monkeypatch):
    from plugins.app_gateway.user_scope import operator_app_gateway_root, user_workspace

    operator_app_gateway_root().mkdir(parents=True, exist_ok=True)
    user_id = "u_upload_retention"
    uploads = user_workspace(user_id) / "uploads"
    uploads.mkdir(parents=True)
    old_file = uploads / "stale.bin"
    old_file.write_bytes(b"old")
    old_ts = time.time() - 120 * 86400
    os.utime(old_file, (old_ts, old_ts))

    cfg = AppGatewayConfig(data_retention_days=90)
    removed = purge_stale_uploads(cfg)
    assert removed >= 1
    assert not old_file.exists()


def test_chat_completions_accepts_cookie_auth(gateway_home):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        auth_mode="dev",
        dev_sms_code="111111",
        require_jwt=True,
        app_key="hermes-local-dev-admin-key",
        web_cookie_auth=True,
    )
    app = create_app(cfg)
    client = TestClient(app)

    seed_dev_sms_otp("13800138000")

    login = client.post(
        "/v1/auth/login",
        json={"phone": "13800138000", "code": "111111"},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    assert login.status_code == 200

    # Cookie JWT must satisfy user routes without X-App-Key / X-User-Token headers.
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "ping"}], "stream": False},
        headers={"X-Hermes-Cookie-Auth": "1"},
    )
    assert resp.status_code != 401 or resp.json().get("detail") != "Invalid app key"


def test_run_data_retention_includes_upload_count(gateway_home, monkeypatch):
    class _FakeDb:
        def prune_sessions(self, **kwargs):
            return 2

    monkeypatch.setattr(
        "hermes_state.get_shared_session_db",
        lambda: _FakeDb(),
    )
    monkeypatch.setattr(
        "plugins.app_gateway.data_retention.purge_stale_uploads",
        lambda _cfg: 5,
    )

    cfg = AppGatewayConfig(data_retention_days=30)
    result = run_data_retention(cfg)
    assert result["pruned_sessions"] == 2
    assert result["uploads_removed"] == 5
