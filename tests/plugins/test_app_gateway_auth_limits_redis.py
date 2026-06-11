"""Redis-backed AuthAbuseLimiter tests."""

from __future__ import annotations

import pytest

from plugins.app_gateway.auth_limits import AuthAbuseLimiter
from plugins.app_gateway.config import AppGatewayConfig


class _FakeRedis:
    """Minimal Redis stub for auth limiter tests."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.kv: dict[str, int] = {}
        self.ttl: dict[str, int] = {}

    def pipeline(self):
        return _FakePipeline(self)

    def zremrangebyscore(self, key, min_score, max_score):
        members = self.zsets.get(key, {})
        self.zsets[key] = {
            m: s for m, s in members.items() if not (float(min_score) <= s <= float(max_score))
        }

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def zadd(self, key, mapping):
        bucket = self.zsets.setdefault(key, {})
        bucket.update({str(m): float(s) for m, s in mapping.items()})

    def expire(self, key, seconds):
        self.ttl[key] = int(seconds)

    def get(self, key):
        return self.kv.get(key)

    def incr(self, key):
        self.kv[key] = int(self.kv.get(key, 0)) + 1
        return self.kv[key]

    def delete(self, key):
        self.kv.pop(key, None)
        self.zsets.pop(key, None)
        self.ttl.pop(key, None)


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

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def execute(self):
        out = []
        for op in self._ops:
            if op[0] == "zremrangebyscore":
                self._redis.zremrangebyscore(op[1], op[2], op[3])
                out.append(None)
            elif op[0] == "zcard":
                out.append(self._redis.zcard(op[1]))
            elif op[0] == "zadd":
                self._redis.zadd(op[1], op[2])
                out.append(len(op[2]))
            elif op[0] == "expire":
                self._redis.expire(op[1], op[2])
                out.append(True)
            elif op[0] == "incr":
                out.append(self._redis.incr(op[1]))
        return out


@pytest.fixture
def auth_cfg():
    return AppGatewayConfig(
        auth_sms_per_ip_per_hour=2,
        auth_sms_per_phone_per_day=2,
        auth_login_failures_per_phone=2,
    )


def test_auth_sms_ip_limit_redis(auth_cfg):
    fake = _FakeRedis()
    lim = AuthAbuseLimiter(auth_cfg, redis_client=fake)
    lim.check_sms_send("1.2.3.4", "+8613800138002")
    lim.check_sms_send("1.2.3.4", "+8613800138003")
    with pytest.raises(ValueError, match="IP"):
        lim.check_sms_send("1.2.3.4", "+8613800138004")
    assert lim.backend == "redis"


def test_login_failure_lockout_redis(auth_cfg):
    fake = _FakeRedis()
    lim = AuthAbuseLimiter(auth_cfg, redis_client=fake)
    lim.record_login_failure("+8613800138005")
    lim.record_login_failure("+8613800138005")
    with pytest.raises(ValueError, match="failed login"):
        lim.check_login_allowed("+8613800138005")
    lim.clear_login_failures("+8613800138005")
    lim.check_login_allowed("+8613800138005")
