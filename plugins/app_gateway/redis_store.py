"""Optional Redis hot cache for conversation tails."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionHotCache:
    """Redis-backed session cache with no-op fallback."""

    def __init__(self, redis_url: str, ttl_seconds: int = 86400) -> None:
        self._url = (redis_url or "").strip()
        self._ttl = max(60, int(ttl_seconds))
        self._client = None
        if self._url:
            self._connect()

    def _connect(self) -> None:
        try:
            import redis  # type: ignore

            self._client = redis.from_url(self._url, decode_responses=True)
            self._client.ping()
            logger.info("App gateway Redis connected")
        except Exception as exc:
            logger.warning("Redis unavailable, using SQLite only: %s", exc)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def _key(self, user_id: str, session_id: str) -> str:
        return f"hermes:app:session:{user_id}:{session_id}"

    def get_history(self, user_id: str, session_id: str) -> Optional[List[Dict[str, Any]]]:
        if not self._client:
            return None
        try:
            raw = self._client.get(self._key(user_id, session_id))
            if not raw:
                return None
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception as exc:
            logger.debug("Redis get_history failed: %s", exc)
        return None

    def set_history(
        self,
        user_id: str,
        session_id: str,
        messages: List[Dict[str, Any]],
    ) -> None:
        if not self._client:
            return
        try:
            self._client.setex(
                self._key(user_id, session_id),
                self._ttl,
                json.dumps(messages, ensure_ascii=False),
            )
        except Exception as exc:
            logger.debug("Redis set_history failed: %s", exc)
