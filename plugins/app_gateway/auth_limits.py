"""IP / phone rate limits for SMS and login (gateway-layer abuse control)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from typing import Any, DefaultDict, List, Optional

from plugins.app_gateway.config import AppGatewayConfig

logger = logging.getLogger(__name__)


class AuthAbuseLimiter:
    """Sliding-window SMS limits and login lockouts with optional Redis backing."""

    def __init__(
        self,
        config: AppGatewayConfig,
        *,
        redis_client: Any = None,
        require_redis: bool = False,
    ) -> None:
        self._sms_ip_hour = int(getattr(config, "auth_sms_per_ip_per_hour", 0) or 0)
        self._sms_phone_day = int(getattr(config, "auth_sms_per_phone_per_day", 0) or 0)
        self._login_fail_max = int(getattr(config, "auth_login_failures_per_phone", 0) or 0)
        self._redis = redis_client
        self._require_redis = bool(require_redis)
        self._lock = threading.Lock()
        self._sms_ip: DefaultDict[str, List[float]] = defaultdict(list)
        self._sms_phone: DefaultDict[str, List[float]] = defaultdict(list)
        self._login_fails: DefaultDict[str, int] = defaultdict(int)
        self._login_fail_reset: DefaultDict[str, float] = defaultdict(float)

    @property
    def backend(self) -> str:
        return "redis" if self._redis_enabled() else "memory"

    def _redis_enabled(self) -> bool:
        return self._redis is not None

    @staticmethod
    def _prune(events: List[float], window_seconds: float, now: float) -> List[float]:
        cutoff = now - window_seconds
        return [t for t in events if t >= cutoff]

    @staticmethod
    def _redis_key(prefix: str, value: str) -> str:
        safe = (value or "unknown").strip() or "unknown"
        return f"hermes:app:auth:{prefix}:{safe}"

    def _check_sliding_window_redis(
        self,
        key: str,
        *,
        window_seconds: int,
        limit: int,
        error_message: str,
    ) -> None:
        now = time.time()
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zcard(key)
            _, count = pipe.execute()
            if int(count or 0) >= limit:
                raise ValueError(error_message)
            member = f"{now}:{uuid.uuid4().hex[:8]}"
            pipe = self._redis.pipeline()
            pipe.zadd(key, {member: now})
            pipe.expire(key, window_seconds)
            pipe.execute()
        except ValueError:
            raise

    def check_sms_send(self, client_ip: str, phone: str) -> None:
        now = time.time()
        ip = (client_ip or "unknown").strip() or "unknown"
        if self._redis_enabled():
            try:
                if self._sms_ip_hour > 0:
                    self._check_sliding_window_redis(
                        self._redis_key("sms:ip", ip),
                        window_seconds=3600,
                        limit=self._sms_ip_hour,
                        error_message="Too many SMS requests from this IP; try again later",
                    )
                if self._sms_phone_day > 0:
                    self._check_sliding_window_redis(
                        self._redis_key("sms:phone", phone),
                        window_seconds=86400,
                        limit=self._sms_phone_day,
                        error_message="Too many SMS requests for this phone; try again tomorrow",
                    )
                return
            except ValueError:
                raise
            except Exception:
                if self._require_redis:
                    raise ValueError("Auth rate limit unavailable; try again later") from None
        with self._lock:
            if self._sms_ip_hour > 0:
                self._sms_ip[ip] = self._prune(self._sms_ip[ip], 3600.0, now)
                if len(self._sms_ip[ip]) >= self._sms_ip_hour:
                    raise ValueError("Too many SMS requests from this IP; try again later")
            if self._sms_phone_day > 0:
                self._sms_phone[phone] = self._prune(
                    self._sms_phone[phone], 86400.0, now
                )
                if len(self._sms_phone[phone]) >= self._sms_phone_day:
                    raise ValueError("Too many SMS requests for this phone; try again tomorrow")
            self._sms_ip[ip].append(now)
            self._sms_phone[phone].append(now)

    def check_login_allowed(self, phone: str) -> None:
        if self._login_fail_max <= 0:
            return
        if self._redis_enabled():
            try:
                key = self._redis_key("login_fail", phone)
                raw = self._redis.get(key)
                if int(raw or 0) >= self._login_fail_max:
                    raise ValueError("Too many failed login attempts; try again later")
                return
            except ValueError:
                raise
            except Exception:
                if self._require_redis:
                    raise ValueError("Login rate limit unavailable; try again later") from None
        now = time.time()
        with self._lock:
            reset_at = self._login_fail_reset.get(phone, 0.0)
            if reset_at and now > reset_at:
                self._login_fails.pop(phone, None)
                self._login_fail_reset.pop(phone, None)
            if self._login_fails.get(phone, 0) >= self._login_fail_max:
                raise ValueError("Too many failed login attempts; try again later")

    def record_login_failure(self, phone: str) -> None:
        if self._login_fail_max <= 0:
            return
        if self._redis_enabled():
            try:
                key = self._redis_key("login_fail", phone)
                pipe = self._redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, 3600)
                pipe.execute()
                return
            except Exception:
                if self._require_redis:
                    return
        now = time.time()
        with self._lock:
            self._login_fails[phone] = self._login_fails.get(phone, 0) + 1
            self._login_fail_reset[phone] = now + 3600.0

    def clear_login_failures(self, phone: str) -> None:
        if self._redis_enabled():
            try:
                self._redis.delete(self._redis_key("login_fail", phone))
                return
            except Exception:
                if self._require_redis:
                    return
        with self._lock:
            self._login_fails.pop(phone, None)
            self._login_fail_reset.pop(phone, None)
