"""Per-user request rate limiting with optional Redis backing."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, Tuple

_WINDOW_SECONDS = 60


class UserRateLimiter:
    """Sliding-window RPM limiter; Redis-backed when a client is provided."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        *,
        redis_client: Any = None,
        require_redis: bool = False,
    ) -> None:
        self._rpm = max(1, int(requests_per_minute))
        self._redis = redis_client
        self._require_redis = bool(require_redis)
        self._lock = threading.Lock()
        self._windows: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    @staticmethod
    def _redis_key(user_id: str) -> str:
        safe = (user_id or "unknown").strip() or "unknown"
        return f"hermes:app:rpm:{safe}"

    def allow(self, user_id: str) -> bool:
        if not user_id:
            return True
        if self._redis is not None:
            try:
                return self._allow_redis(user_id)
            except Exception:
                if self._require_redis:
                    return False
        return self._allow_memory(user_id)

    def _allow_redis(self, user_id: str) -> bool:
        now = time.time()
        key = self._redis_key(user_id)
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)
        pipe.zcard(key)
        _, count = pipe.execute()
        if int(count or 0) >= self._rpm:
            return False
        member = f"{now}:{uuid.uuid4().hex[:8]}"
        pipe = self._redis.pipeline()
        pipe.zadd(key, {member: now})
        pipe.expire(key, _WINDOW_SECONDS + 5)
        pipe.execute()
        return True

    def _allow_memory(self, user_id: str) -> bool:
        now = int(time.time())
        window = now // _WINDOW_SECONDS
        with self._lock:
            count, w = self._windows[user_id]
            if w != window:
                self._windows[user_id] = (1, window)
                return True
            if count >= self._rpm:
                return False
            self._windows[user_id] = (count + 1, window)
            return True
