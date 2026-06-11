"""P0/P1 App Gateway optimization tests."""

from __future__ import annotations

import pytest

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.quotas import UserQuotaManager
from plugins.app_gateway.skill_catalog_cache import (
    invalidate_skill_catalog_cache,
    should_sync_public_catalog,
    skills_catalog_fingerprint,
)
from toolsets import resolve_toolset


def test_app_gateway_toolset_excludes_web_search():
    tools = set(resolve_toolset("hermes-app-gateway"))
    assert "web_search" not in tools
    assert "read_file" in tools
    assert "vision_analyze" in tools


def test_skill_catalog_fingerprint_skips_resync():
    invalidate_skill_catalog_cache()
    meta = [{"name": "alpha", "version": 1, "updated_at": 1.0, "status": "active"}]
    fp = skills_catalog_fingerprint(meta)
    assert should_sync_public_catalog(fp) is True
    assert should_sync_public_catalog(fp) is False


def test_user_quota_manager_redis_backend():
    class _Pipe:
        def __init__(self, redis):
            self._redis = redis
            self._ops = []

        def get(self, key):
            self._ops.append(("get", key))
            return self

        def incr(self, key):
            self._ops.append(("incr", key))
            return self

        def incrby(self, key, amount):
            self._ops.append(("incrby", key, amount))
            return self

        def expire(self, key, ttl):
            self._ops.append(("expire", key, ttl))
            return self

        def execute(self):
            out = []
            for op in self._ops:
                if op[0] == "get":
                    out.append(self._redis.store.get(op[1], 0))
                elif op[0] == "incr":
                    out.append(self._redis.incr(op[1]))
                elif op[0] == "incrby":
                    out.append(self._redis.incrby(op[1], op[2]))
            self._ops = []
            return out

    class FakeRedis:
        def __init__(self):
            self.store = {}

        def pipeline(self):
            return _Pipe(self)

        def get(self, key):
            return self.store.get(key, 0)

        def incr(self, key):
            self.store[key] = int(self.store.get(key, 0)) + 1
            return self.store[key]

        def incrby(self, key, amount):
            self.store[key] = int(self.store.get(key, 0)) + int(amount)
            return self.store[key]

        def expire(self, key, ttl):
            return True

        def delete(self, key):
            self.store.pop(key, None)

        def decr(self, key):
            self.store[key] = max(0, int(self.store.get(key, 0)) - 1)
            return self.store[key]

    fake = FakeRedis()
    cfg = AppGatewayConfig(max_concurrent_chats_per_user=1)
    q = UserQuotaManager(cfg, redis_client=fake)
    q.check_and_acquire_chat("u1")
    snap = q.usage_snapshot("u1")
    assert snap["backend"] == "redis"
    assert snap["active_chats"] == 1
    q.release_chat("u1")
    assert q.usage_snapshot("u1")["active_chats"] == 0


def test_me_storage_uses_local_snapshot(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.server import create_app
    from plugins.app_gateway.user_scope import ensure_user_home, user_workspace

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    secret = "secret"
    cfg = AppGatewayConfig(require_jwt=True, jwt_secret=secret)
    app = create_app(cfg)
    ensure_user_home("storage-user", include_global_skills=False)
    (user_workspace("storage-user") / "note.txt").write_bytes(b"hello")
    token = encode_hs256_jwt(
        {"sub": "storage-user", "session_id": "app", "exp": 9999999999},
        secret,
    )

    resp = TestClient(app).get(
        "/v1/me/storage",
        headers={"X-User-Token": token},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["bytes_used"] == 5
    assert body.get("source") == "local"


def test_health_reports_upload_queue_stats():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    app = create_app(AppGatewayConfig())
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "workspace_upload_queue" in body
    assert "workers" in body["workspace_upload_queue"]
