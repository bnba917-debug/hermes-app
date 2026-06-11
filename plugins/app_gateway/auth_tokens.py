"""Access + refresh token issuance with optional Redis-backed refresh rotation."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

from plugins.app_gateway.auth import encode_hs256_jwt
from plugins.app_gateway.config import AppGatewayConfig

logger = logging.getLogger(__name__)

_REFRESH_PREFIX = "hermes:app:auth:refresh:"
_USER_INDEX_PREFIX = "hermes:app:auth:refresh:user:"
_FAMILY_PREFIX = "hermes:app:auth:refresh:family:"
_USED_PREFIX = "hermes:app:auth:refresh:used:"


class RefreshTokenError(ValueError):
    """Invalid, expired, or revoked refresh token."""


class RefreshTokenReuseError(RefreshTokenError):
    """Rotated refresh token presented again — family revoked."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: Optional[str]
    expires_in: int
    refresh_expires_in: Optional[int] = None


def refresh_tokens_enabled(config: AppGatewayConfig) -> bool:
    return bool(getattr(config, "refresh_tokens_enabled", True))


def access_ttl_seconds(config: AppGatewayConfig) -> int:
    if refresh_tokens_enabled(config):
        minutes = int(getattr(config, "jwt_access_ttl_minutes", 120) or 120)
        return max(60, minutes * 60)
    hours = max(1, int(getattr(config, "jwt_ttl_hours", 720) or 720))
    return hours * 3600


def refresh_ttl_seconds(config: AppGatewayConfig) -> int:
    days = max(1, int(getattr(config, "jwt_refresh_ttl_days", 30) or 30))
    return days * 86400


def issue_access_token(
    config: AppGatewayConfig,
    *,
    user_id: str,
    phone: str,
    session_id: str = "app",
    device_id: Optional[str] = None,
) -> str:
    if not config.jwt_secret:
        raise RuntimeError("APP_GATEWAY_JWT_SECRET is not configured")
    now = int(time.time())
    ttl = access_ttl_seconds(config)
    payload: Dict[str, Any] = {
        "sub": user_id,
        "phone": phone,
        "typ": "access",
        config.claim_session_id: session_id,
        "iat": now,
        "exp": now + ttl,
    }
    if device_id:
        payload[config.claim_device_id] = device_id
    return encode_hs256_jwt(payload, config.jwt_secret)


class RefreshTokenStore:
    """Opaque refresh tokens with rotation; Redis when available, in-memory fallback."""

    def __init__(self, config: AppGatewayConfig, *, redis_client: Any = None, require_redis: bool = False) -> None:
        self._config = config
        self._redis = redis_client
        self._require_redis = bool(require_redis)
        self._lock = threading.Lock()
        self._memory: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._memory_user: Dict[str, Set[str]] = {}
        self._memory_family: Dict[str, Set[str]] = {}
        self._memory_used: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    @property
    def active(self) -> bool:
        return refresh_tokens_enabled(self._config)

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _redis_key(self, token_hash: str) -> str:
        return f"{_REFRESH_PREFIX}{token_hash}"

    def _store_record(self, token_hash: str, record: Dict[str, Any], ttl: int) -> None:
        if self._redis is not None:
            try:
                self._redis.setex(
                    self._redis_key(token_hash),
                    ttl,
                    json.dumps(record, ensure_ascii=False),
                )
                return
            except Exception as exc:
                logger.warning("Redis refresh store failed, using memory: %s", exc)
                if self._require_redis:
                    raise RefreshTokenError("refresh token store unavailable") from exc
        expires_at = time.time() + ttl
        with self._lock:
            self._memory[token_hash] = (expires_at, dict(record))

    def _load_record(self, token_hash: str) -> Optional[Dict[str, Any]]:
        if self._redis is not None:
            try:
                raw = self._redis.get(self._redis_key(token_hash))
                if not raw:
                    return None
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            except Exception as exc:
                logger.debug("Redis refresh load failed: %s", exc)
                if self._require_redis:
                    return None
        with self._lock:
            entry = self._memory.get(token_hash)
            if not entry:
                return None
            expires_at, record = entry
            if expires_at <= time.time():
                self._memory.pop(token_hash, None)
                return None
            return dict(record)

    def _delete_record(self, token_hash: str) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(self._redis_key(token_hash))
            except Exception as exc:
                logger.debug("Redis refresh delete failed: %s", exc)
        with self._lock:
            self._memory.pop(token_hash, None)

    def _track_indices(
        self,
        *,
        user_id: str,
        token_hash: str,
        family_id: str,
        ttl: int,
    ) -> None:
        if self._redis is not None:
            try:
                user_key = f"{_USER_INDEX_PREFIX}{user_id}"
                family_key = f"{_FAMILY_PREFIX}{family_id}"
                pipe = self._redis.pipeline()
                pipe.sadd(user_key, token_hash)
                pipe.expire(user_key, ttl)
                pipe.sadd(family_key, token_hash)
                pipe.expire(family_key, ttl)
                pipe.execute()
                return
            except Exception as exc:
                logger.debug("Redis refresh index failed: %s", exc)
                if self._require_redis:
                    raise RefreshTokenError("refresh token store unavailable") from exc
        with self._lock:
            self._memory_user.setdefault(user_id, set()).add(token_hash)
            self._memory_family.setdefault(family_id, set()).add(token_hash)

    def _mark_used(self, token_hash: str, record: Dict[str, Any], ttl: int) -> None:
        payload = {
            "family_id": str(record.get("family_id") or ""),
            "user_id": str(record.get("user_id") or ""),
        }
        if self._redis is not None:
            try:
                self._redis.setex(
                    f"{_USED_PREFIX}{token_hash}",
                    ttl,
                    json.dumps(payload, ensure_ascii=False),
                )
                return
            except Exception as exc:
                logger.debug("Redis refresh used marker failed: %s", exc)
        expires_at = time.time() + ttl
        with self._lock:
            self._memory_used[token_hash] = (expires_at, payload)

    def _used_marker(self, token_hash: str) -> Optional[Dict[str, Any]]:
        if self._redis is not None:
            try:
                raw = self._redis.get(f"{_USED_PREFIX}{token_hash}")
                if not raw:
                    return None
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            except Exception:
                return None
        with self._lock:
            entry = self._memory_used.get(token_hash)
            if not entry:
                return None
            expires_at, payload = entry
            if expires_at <= time.time():
                self._memory_used.pop(token_hash, None)
                return None
            return dict(payload)

    def _revoke_family(self, family_id: str, *, user_id: str = "") -> None:
        if not family_id:
            return
        if self._redis is not None:
            try:
                family_key = f"{_FAMILY_PREFIX}{family_id}"
                members = list(self._redis.smembers(family_key) or [])
                pipe = self._redis.pipeline()
                for token_hash in members:
                    pipe.delete(self._redis_key(str(token_hash)))
                    pipe.delete(f"{_USED_PREFIX}{token_hash}")
                pipe.delete(family_key)
                if user_id:
                    pipe.delete(f"{_USER_INDEX_PREFIX}{user_id}")
                pipe.execute()
            except Exception as exc:
                logger.debug("Redis refresh family revoke failed: %s", exc)
        with self._lock:
            for token_hash in list(self._memory_family.get(family_id, set())):
                self._memory.pop(token_hash, None)
            self._memory_family.pop(family_id, None)
            if user_id:
                self._memory_user.pop(user_id, None)

    def revoke_all_for_user(self, user_id: str) -> None:
        uid = (user_id or "").strip()
        if not uid:
            return
        if self._redis is not None:
            try:
                user_key = f"{_USER_INDEX_PREFIX}{uid}"
                members = list(self._redis.smembers(user_key) or [])
                pipe = self._redis.pipeline()
                for token_hash in members:
                    pipe.delete(self._redis_key(str(token_hash)))
                    pipe.delete(f"{_USED_PREFIX}{token_hash}")
                pipe.delete(user_key)
                pipe.execute()
            except Exception as exc:
                logger.debug("Redis refresh user revoke failed: %s", exc)
        with self._lock:
            for token_hash in list(self._memory_user.get(uid, set())):
                self._memory.pop(token_hash, None)
            self._memory_user.pop(uid, None)

    def create(
        self,
        *,
        user_id: str,
        phone: str,
        session_id: str,
        device_id: Optional[str],
        family_id: Optional[str] = None,
    ) -> str:
        plain = secrets.token_urlsafe(48)
        token_hash = self._hash_token(plain)
        fid = (family_id or "").strip() or secrets.token_hex(16)
        ttl = refresh_ttl_seconds(self._config)
        record = {
            "user_id": user_id,
            "phone": phone,
            "session_id": session_id,
            "device_id": device_id,
            "family_id": fid,
            "created_at": int(time.time()),
        }
        self._store_record(token_hash, record, ttl)
        self._track_indices(user_id=user_id, token_hash=token_hash, family_id=fid, ttl=ttl)
        return plain

    def consume(self, refresh_token: str) -> Dict[str, Any]:
        token = (refresh_token or "").strip()
        if not token:
            raise RefreshTokenError("refresh_token is required")
        token_hash = self._hash_token(token)
        used = self._used_marker(token_hash)
        if used is not None:
            self._revoke_family(
                str(used.get("family_id") or ""),
                user_id=str(used.get("user_id") or ""),
            )
            raise RefreshTokenReuseError(
                "refresh token reuse detected; all sessions revoked"
            )
        record = self._load_record(token_hash)
        if not record:
            raise RefreshTokenError("invalid or expired refresh token")
        ttl = refresh_ttl_seconds(self._config)
        self._delete_record(token_hash)
        self._mark_used(token_hash, record, ttl)
        return record

    def revoke(self, refresh_token: str) -> None:
        token = (refresh_token or "").strip()
        if not token:
            return
        self._delete_record(self._hash_token(token))


class AuthTokenService:
    """Issue and rotate login tokens."""

    def __init__(self, config: AppGatewayConfig, *, redis_client: Any = None, require_redis: bool = False) -> None:
        self._config = config
        self._refresh = RefreshTokenStore(config, redis_client=redis_client, require_redis=require_redis)

    @property
    def refresh_backend(self) -> str:
        return self._refresh.backend

    @property
    def refresh_enabled(self) -> bool:
        return self._refresh.active

    def issue_login_tokens(
        self,
        *,
        user_id: str,
        phone: str,
        session_id: str = "app",
        device_id: Optional[str] = None,
        family_id: Optional[str] = None,
    ) -> TokenPair:
        access = issue_access_token(
            self._config,
            user_id=user_id,
            phone=phone,
            session_id=session_id,
            device_id=device_id,
        )
        expires_in = access_ttl_seconds(self._config)
        if not self._refresh.active:
            return TokenPair(
                access_token=access,
                refresh_token=None,
                expires_in=expires_in,
            )
        refresh = self._refresh.create(
            user_id=user_id,
            phone=phone,
            session_id=session_id,
            device_id=device_id,
            family_id=family_id,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
            refresh_expires_in=refresh_ttl_seconds(self._config),
        )

    def refresh_tokens(self, refresh_token: str) -> TokenPair:
        if not self._refresh.active:
            raise RefreshTokenError("refresh tokens are disabled")
        record = self._refresh.consume(refresh_token)
        user_id = str(record.get("user_id") or "").strip()
        phone = str(record.get("phone") or "").strip()
        if not user_id or not phone:
            raise RefreshTokenError("invalid refresh token payload")
        session_id = str(record.get("session_id") or "app").strip() or "app"
        device_raw = record.get("device_id")
        device_id = str(device_raw).strip() if device_raw else None
        return self.issue_login_tokens(
            user_id=user_id,
            phone=phone,
            session_id=session_id,
            device_id=device_id,
            family_id=str(record.get("family_id") or "").strip() or None,
        )

    def revoke_refresh_token(self, refresh_token: str) -> None:
        self._refresh.revoke(refresh_token)

    def revoke_all_user_tokens(self, user_id: str) -> None:
        self._refresh.revoke_all_for_user(user_id)
