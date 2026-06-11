"""Redis-backed RPM, production Redis policy, and metrics."""

from __future__ import annotations

import pytest

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.metrics import counter_inc, gauge_set, normalize_path, render_prometheus
from plugins.app_gateway.rate_limit import UserRateLimiter
from plugins.app_gateway.redis_policy import (
    RedisRequiredError,
    require_redis_for_production,
    validate_app_gateway_redis,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._ops.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zcard(self, key):
        self._ops.append(("zcard", key))
        return self

    def zadd(self, key, mapping):
        self._ops.append(("zadd", key, mapping))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self):
        out = []
        for op in self._ops:
            if op[0] == "zremrangebyscore":
                key, _, max_score = op[1], op[2], op[3]
                members = self._redis.zsets.get(key, {})
                self._redis.zsets[key] = {
                    m: s for m, s in members.items() if s > float(max_score)
                }
                out.append(None)
            elif op[0] == "zcard":
                out.append(len(self._redis.zsets.get(op[1], {})))
            elif op[0] == "zadd":
                bucket = self._redis.zsets.setdefault(op[1], {})
                bucket.update({str(m): float(s) for m, s in op[2].items()})
                out.append(len(op[2]))
            elif op[0] == "expire":
                out.append(True)
        return out


def test_rate_limit_redis_backend():
    fake = _FakeRedis()
    lim = UserRateLimiter(2, redis_client=fake)
    assert lim.allow("alice")
    assert lim.allow("alice")
    assert not lim.allow("alice")
    assert lim.backend == "redis"


def test_rate_limit_fail_closed_when_redis_required():
    lim = UserRateLimiter(60, redis_client=_BrokenRedis(), require_redis=True)
    assert lim.allow("alice") is False


class _BrokenRedis:
    def pipeline(self):
        raise RuntimeError("redis down")


def test_require_redis_when_postgres_only():
    cfg = AppGatewayConfig(postgres_only=True)
    assert require_redis_for_production(cfg) is True


def test_validate_redis_required_missing_url():
    cfg = AppGatewayConfig(postgres_only=True, redis_url="")
    cache = _CacheStub(available=False)
    with pytest.raises(RedisRequiredError, match="redis_url"):
        validate_app_gateway_redis(cfg, cache)


def test_validate_redis_required_unreachable():
    cfg = AppGatewayConfig(
        postgres_only=True,
        redis_url="redis://127.0.0.1:6379/0",
    )
    cache = _CacheStub(available=False)
    with pytest.raises(RedisRequiredError, match="unreachable"):
        validate_app_gateway_redis(cfg, cache)


class _CacheStub:
    def __init__(self, *, available: bool) -> None:
        self.available = available


def test_metrics_render():
    counter_inc("hermes_app_gateway_http_requests_total", labels={"route": "/health"})
    gauge_set("hermes_app_gateway_agent_active", 3)
    body = render_prometheus()
    assert "hermes_app_gateway_http_requests_total" in body
    assert "hermes_app_gateway_agent_active 3" in body


def test_metrics_normalize_path():
    assert normalize_path("/v1/auth/login") == "/v1/auth/*"
    assert normalize_path("/v1/sessions/abc/messages") == "/v1/sessions/*"


def test_health_degraded_without_redis_in_production(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        require_jwt=False,
        jwt_secret="secret",
        postgres_only=True,
        postgres_url="postgresql://localhost/hermes",
        audit_backend="postgres",
        redis_url="",
    )
    vector = MagicMock(enabled=True)
    with patch("plugins.app_gateway.postgres_policy.validate_app_gateway_postgres_only"), patch(
        "plugins.app_gateway.redis_policy.validate_app_gateway_redis"
    ), patch(
        "plugins.app_gateway.audit_backends.PostgresAuditBackend",
        return_value=MagicMock(),
    ):
        app = create_app(cfg, vector_memory=vector)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["require_redis"] is True
    assert body["status"] == "degraded"


def test_metrics_endpoint():
    pytest.importorskip("fastapi")
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(require_jwt=False, jwt_secret="secret", metrics_enabled=True)
    with patch("plugins.app_gateway.redis_policy.validate_app_gateway_redis"):
        app = create_app(cfg)
    client = TestClient(app)
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "hermes_app_gateway_http_requests_total" in resp.text


def test_probe_redis():
    from plugins.app_gateway.health_checks import probe_redis

    assert probe_redis("")["configured"] is False
    assert probe_redis("redis://invalid-host-no-connect:6399/0")["configured"] is True
    assert probe_redis("redis://invalid-host-no-connect:6399/0")["ok"] is False
