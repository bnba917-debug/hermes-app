"""Per-user daily quotas and concurrent chat limits for App Gateway."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional, Tuple

from plugins.app_gateway.config import AppGatewayConfig


class QuotaExceeded(Exception):
    def __init__(self, code: str, message: str, *, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass
class _DailyBucket:
    chats: int = 0
    tokens: int = 0


class UserQuotaManager:
    """Daily chat/token limits with optional Redis backing for multi-instance deploys."""

    def __init__(self, config: AppGatewayConfig, *, redis_client: Any = None, require_redis: bool = False) -> None:
        self._daily_chat_limit = int(getattr(config, "daily_chat_limit", 0) or 0)
        self._daily_token_limit = int(getattr(config, "daily_token_limit", 0) or 0)
        self._max_concurrent = int(getattr(config, "max_concurrent_chats_per_user", 0) or 0)
        stream_timeout = float(getattr(config, "sse_stream_timeout_seconds", 600) or 600)
        self._active_chat_ttl = int(stream_timeout) + 120
        self._redis = redis_client
        self._require_redis = bool(require_redis)
        self._lock = threading.Lock()
        self._daily: Dict[Tuple[str, str], _DailyBucket] = {}
        self._active: Dict[str, int] = {}

    @staticmethod
    def _today_key() -> str:
        return date.today().isoformat()

    def _redis_enabled(self) -> bool:
        return self._redis is not None

    def _redis_daily_key(self, user_id: str, field: str) -> str:
        return f"hermes:app:quota:{user_id}:{self._today_key()}:{field}"

    def _redis_active_key(self, user_id: str) -> str:
        return f"hermes:app:quota:{user_id}:active"

    def _bucket(self, user_id: str) -> _DailyBucket:
        key = (user_id, self._today_key())
        if key not in self._daily:
            self._daily[key] = _DailyBucket()
        return self._daily[key]

    def _redis_get_int(self, key: str) -> int:
        try:
            raw = self._redis.get(key)
            return int(raw or 0)
        except Exception:
            return 0

    def _reconcile_stale_active(self, user_id: str) -> None:
        """Drop orphaned active-chat counters (e.g. gateway restart mid-stream)."""
        try:
            from plugins.app_gateway.run_registry import active_run_count
        except Exception:
            return
        if active_run_count(user_id) > 0:
            return
        if self._redis_enabled():
            try:
                active_key = self._redis_active_key(user_id)
                if self._redis_get_int(active_key) > 0:
                    self._redis.delete(active_key)
            except Exception:
                pass
        with self._lock:
            if self._active.get(user_id, 0) > 0:
                self._active.pop(user_id, None)

    def check_and_acquire_chat(self, user_id: str) -> None:
        """Raise QuotaExceeded if user cannot start another chat turn."""
        self._reconcile_stale_active(user_id)
        if self._redis_enabled():
            self._check_and_acquire_chat_redis(user_id)
            return
        self._check_and_acquire_chat_memory(user_id)

    def _check_and_acquire_chat_redis(self, user_id: str) -> None:
        chats_key = self._redis_daily_key(user_id, "chats")
        tokens_key = self._redis_daily_key(user_id, "tokens")
        active_key = self._redis_active_key(user_id)
        try:
            pipe = self._redis.pipeline()
            pipe.get(active_key)
            pipe.get(chats_key)
            pipe.get(tokens_key)
            active_raw, chats_raw, tokens_raw = pipe.execute()
            active = int(active_raw or 0)
            chats = int(chats_raw or 0)
            tokens = int(tokens_raw or 0)
            if self._max_concurrent > 0 and active >= self._max_concurrent:
                raise QuotaExceeded(
                    "concurrent_limit",
                    f"At most {self._max_concurrent} concurrent chats per user",
                    retry_after=30,
                )
            if self._daily_chat_limit > 0 and chats >= self._daily_chat_limit:
                raise QuotaExceeded(
                    "daily_chat_limit",
                    f"Daily chat limit reached ({self._daily_chat_limit})",
                    retry_after=3600,
                )
            if self._daily_token_limit > 0 and tokens >= self._daily_token_limit:
                raise QuotaExceeded(
                    "daily_token_limit",
                    f"Daily token limit reached ({self._daily_token_limit})",
                    retry_after=3600,
                )
            pipe = self._redis.pipeline()
            pipe.incr(active_key)
            pipe.incr(chats_key)
            pipe.expire(active_key, self._active_chat_ttl)
            pipe.expire(chats_key, 86400)
            pipe.expire(tokens_key, 86400)
            pipe.execute()
        except QuotaExceeded:
            raise
        except Exception:
            if self._require_redis:
                raise QuotaExceeded(
                    "quota_unavailable",
                    "Quota service unavailable; try again later",
                    retry_after=30,
                ) from None
            self._check_and_acquire_chat_memory(user_id)

    def _check_and_acquire_chat_memory(self, user_id: str) -> None:
        with self._lock:
            if self._max_concurrent > 0:
                active = self._active.get(user_id, 0)
                if active >= self._max_concurrent:
                    raise QuotaExceeded(
                        "concurrent_limit",
                        f"At most {self._max_concurrent} concurrent chats per user",
                        retry_after=30,
                    )
            bucket = self._bucket(user_id)
            if self._daily_chat_limit > 0 and bucket.chats >= self._daily_chat_limit:
                raise QuotaExceeded(
                    "daily_chat_limit",
                    f"Daily chat limit reached ({self._daily_chat_limit})",
                    retry_after=3600,
                )
            if self._daily_token_limit > 0 and bucket.tokens >= self._daily_token_limit:
                raise QuotaExceeded(
                    "daily_token_limit",
                    f"Daily token limit reached ({self._daily_token_limit})",
                    retry_after=3600,
                )
            self._active[user_id] = self._active.get(user_id, 0) + 1
            bucket.chats += 1

    def release_chat(self, user_id: str) -> None:
        if self._redis_enabled():
            try:
                active_key = self._redis_active_key(user_id)
                current = self._redis_get_int(active_key)
                if current <= 1:
                    self._redis.delete(active_key)
                else:
                    self._redis.decr(active_key)
                return
            except Exception:
                pass
        with self._lock:
            n = self._active.get(user_id, 0)
            if n <= 1:
                self._active.pop(user_id, None)
            else:
                self._active[user_id] = n - 1

    def record_tokens(self, user_id: str, tokens: int) -> None:
        if tokens <= 0:
            return
        if self._redis_enabled():
            try:
                key = self._redis_daily_key(user_id, "tokens")
                pipe = self._redis.pipeline()
                pipe.incrby(key, int(tokens))
                pipe.expire(key, 86400)
                pipe.execute()
                return
            except Exception:
                pass
        with self._lock:
            self._bucket(user_id).tokens += int(tokens)

    def usage_snapshot(self, user_id: str) -> dict:
        if self._redis_enabled():
            try:
                return {
                    "date": self._today_key(),
                    "chats_today": self._redis_get_int(self._redis_daily_key(user_id, "chats")),
                    "tokens_today": self._redis_get_int(self._redis_daily_key(user_id, "tokens")),
                    "active_chats": self._redis_get_int(self._redis_active_key(user_id)),
                    "daily_chat_limit": self._daily_chat_limit,
                    "daily_token_limit": self._daily_token_limit,
                    "max_concurrent_chats_per_user": self._max_concurrent,
                    "backend": "redis",
                }
            except Exception:
                pass
        with self._lock:
            b = self._bucket(user_id)
            return {
                "date": self._today_key(),
                "chats_today": b.chats,
                "tokens_today": b.tokens,
                "active_chats": self._active.get(user_id, 0),
                "daily_chat_limit": self._daily_chat_limit,
                "daily_token_limit": self._daily_token_limit,
                "max_concurrent_chats_per_user": self._max_concurrent,
                "backend": "memory",
            }
