"""P2: retention, account delete, refresh reuse, storage snapshot."""

from __future__ import annotations

import json
import time

import pytest

from plugins.app_gateway.auth_tokens import (
    AuthTokenService,
    RefreshTokenReuseError,
)
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.data_retention import maybe_run_data_retention, run_data_retention

SECRET = "test-secret-key"


class _FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttl: dict[str, int] = {}

    def setex(self, key, ttl, value):
        self.kv[key] = value if isinstance(value, str) else str(value)
        self.ttl[key] = int(ttl)

    def get(self, key):
        return self.kv.get(key)

    def delete(self, *keys):
        for key in keys:
            self.kv.pop(key, None)
            self.sets.pop(key, None)
            self.ttl.pop(key, None)

    def exists(self, key):
        return key in self.kv

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(str(member))

    def smembers(self, key):
        return self.sets.get(key, set())

    def expire(self, key, seconds):
        self.ttl[key] = int(seconds)

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops = []

    def sadd(self, key, member):
        self._ops.append(("sadd", key, member))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def delete(self, *keys):
        self._ops.append(("delete", *keys))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "sadd":
                self._redis.sadd(op[1], op[2])
            elif op[0] == "expire":
                self._redis.expire(op[1], op[2])
            elif op[0] == "delete":
                self._redis.delete(*op[1:])
        return [True] * len(self._ops)


@pytest.fixture
def auth_config():
    return AppGatewayConfig(
        jwt_secret=SECRET,
        refresh_tokens_enabled=True,
        jwt_access_ttl_minutes=60,
        jwt_refresh_ttl_days=7,
    )


def test_refresh_token_reuse_revokes_family(auth_config):
    fake = _FakeRedis()
    svc = AuthTokenService(auth_config, redis_client=fake)
    first = svc.issue_login_tokens(
        user_id="u_test",
        phone="8613800138000",
        session_id="app",
    )
    old_refresh = first.refresh_token
    assert old_refresh
    svc.refresh_tokens(old_refresh)
    with pytest.raises(RefreshTokenReuseError, match="reuse"):
        svc.refresh_tokens(old_refresh)


def test_revoke_all_user_tokens(auth_config):
    fake = _FakeRedis()
    svc = AuthTokenService(auth_config, redis_client=fake)
    pair = svc.issue_login_tokens(user_id="u1", phone="8613800138000")
    assert pair.refresh_token
    svc.revoke_all_user_tokens("u1")
    from plugins.app_gateway.auth_tokens import RefreshTokenError

    with pytest.raises(RefreshTokenError):
        svc.refresh_tokens(pair.refresh_token)


def test_data_retention_prunes_app_gateway_sessions(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    class _FakeDb:
        def __init__(self) -> None:
            self.kwargs = None

        def prune_sessions(self, **kwargs):
            self.kwargs = kwargs
            return 3

    fake_db = _FakeDb()
    monkeypatch.setattr(
        "hermes_state.get_shared_session_db",
        lambda: fake_db,
    )

    cfg = AppGatewayConfig(data_retention_days=90)
    result = run_data_retention(cfg)
    assert result["pruned_sessions"] == 3
    assert fake_db.kwargs["source"] == "app_gateway"
    assert fake_db.kwargs["older_than_days"] == 90


def test_maybe_run_data_retention_respects_interval(tmp_path, monkeypatch):
    from plugins.app_gateway.user_scope import operator_app_gateway_root

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    operator_app_gateway_root().mkdir(parents=True, exist_ok=True)
    stamp = operator_app_gateway_root() / ".last_retention_run"
    stamp.write_text(str(time.time()), encoding="utf-8")

    cfg = AppGatewayConfig(data_retention_days=30, data_retention_interval_hours=24)
    out = maybe_run_data_retention(cfg)
    assert out["skipped"] is True


def test_delete_me_endpoint(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.server import create_app

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    cfg = AppGatewayConfig(
        jwt_secret=SECRET,
        require_jwt=True,
        refresh_tokens_enabled=True,
        delete_account_sms_verify=False,
    )
    with patch("plugins.app_gateway.redis_policy.validate_app_gateway_redis"):
        app = create_app(cfg, vector_memory=MagicMock(enabled=False))
    client = TestClient(app)

    token = encode_hs256_jwt(
        {
            "sub": "u_delete_me",
            "typ": "access",
            "session_id": "app",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
    )

    with patch(
        "plugins.app_gateway.account_compliance.delete_user_account",
        return_value={"ok": True, "user_id": "u_delete_me"},
    ) as delete_mock:
        resp = client.request(
            "DELETE",
            "/v1/me",
            headers={"X-User-Token": token},
            json={"confirm": True},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    delete_mock.assert_called_once()


def test_logout_all_endpoint(auth_config):
    pytest.importorskip("fastapi")
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(jwt_secret=SECRET, require_jwt=True)
    with patch("plugins.app_gateway.redis_policy.validate_app_gateway_redis"):
        app = create_app(cfg)
    client = TestClient(app)
    token = encode_hs256_jwt(
        {
            "sub": "u1",
            "typ": "access",
            "session_id": "app",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
    )
    resp = client.post(
        "/v1/auth/logout/all",
        headers={"X-User-Token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_upload_queue_retries_then_fails(monkeypatch):
    from plugins.app_gateway.workspace_upload_queue import (
        WorkspaceUploadQueue,
        reset_workspace_upload_queue,
    )

    reset_workspace_upload_queue()
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("upload failed")

    monkeypatch.setattr(
        "plugins.app_gateway.workspace_minio.upload_remote_bytes",
        _boom,
    )
    monkeypatch.setattr(
        "plugins.app_gateway.workspace_upload_queue._max_upload_retries",
        lambda: 1,
    )

    queue = WorkspaceUploadQueue(workers=1)
    queue.enqueue_bytes("u1", "uploads/a.txt", b"hello")
    assert queue.wait_until_idle(timeout=8.0)
    stats = queue.stats()
    assert stats["total_failed"] >= 1
    assert "uploads/a.txt" in queue.failed_relative_paths("u1")


def test_storage_snapshot_includes_queue_meta(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    from plugins.app_gateway.storage_snapshot import storage_usage_snapshot

    uid = "u_storage"
    from plugins.app_gateway.user_scope import ensure_user_home

    ensure_user_home(uid, include_global_skills=False)
    snap = storage_usage_snapshot(uid)
    assert "bytes_used" in snap
    assert "pending_uploads" in snap
    assert "failed_uploads" in snap
