"""PostgreSQL-backed per-user config and env secrets for App Gateway."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_PROFILES_DDL = """
CREATE TABLE IF NOT EXISTS hermes_app_user_profiles (
    user_id TEXT PRIMARY KEY,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    env_secrets JSONB NOT NULL DEFAULT '{}'::jsonb,
    initialized_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
"""

_DEFAULT_USER_CONFIG: Dict[str, Any] = {
    "model": {
        "provider": "openrouter",
        "default": "",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "skills": {"disabled": []},
    "approvals": {"mode": "off"},
    "delegation": {
        "max_concurrent_children": 3,
        "orchestrator_enabled": False,
        "subagent_auto_approve": True,
    },
    "app_gateway": {},
}


def use_postgres_user_data() -> bool:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        return bool(load_app_gateway_config().postgres_url)
    except Exception:
        return False


class UserDataStore:
    """Per-user config + secrets in PostgreSQL."""

    def __init__(self, dsn: str) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise RuntimeError("PostgreSQL DSN is required for user data store")
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL user data store requires psycopg. "
                "Install: uv pip install -e '.[postgres]'"
            ) from exc
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_PROFILES_DDL)
                conn.commit()

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM hermes_app_user_profiles WHERE user_id = %s",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return {
                        "user_id": row["user_id"],
                        "config": dict(row["config"] or {}),
                        "env_secrets": dict(row["env_secrets"] or {}),
                        "initialized_at": float(row["initialized_at"]),
                        "updated_at": float(row["updated_at"]),
                    }

    def ensure_profile(self, user_id: str) -> Dict[str, Any]:
        existing = self.get_profile(user_id)
        if existing:
            return existing
        now = time.time()
        cfg = copy.deepcopy(_DEFAULT_USER_CONFIG)
        cfg["app_gateway"] = {"user_id": user_id}
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hermes_app_user_profiles
                            (user_id, config, env_secrets, initialized_at, updated_at)
                        VALUES (%s, %s::jsonb, %s::jsonb, %s, %s)
                        ON CONFLICT (user_id) DO NOTHING
                        """,
                        (user_id, json.dumps(cfg), json.dumps({}), now, now),
                    )
                conn.commit()
        return self.get_profile(user_id) or {
            "user_id": user_id,
            "config": cfg,
            "env_secrets": {},
            "initialized_at": now,
            "updated_at": now,
        }

    def save_profile(
        self,
        user_id: str,
        *,
        config: Dict[str, Any],
        env_secrets: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        existing = self.ensure_profile(user_id)
        secrets = env_secrets if env_secrets is not None else existing["env_secrets"]
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE hermes_app_user_profiles
                        SET config = %s::jsonb,
                            env_secrets = %s::jsonb,
                            updated_at = %s
                        WHERE user_id = %s
                        """,
                        (json.dumps(config), json.dumps(secrets), now, user_id),
                    )
                conn.commit()
        profile = self.get_profile(user_id)
        assert profile is not None
        return profile

    def delete_profile(self, user_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM hermes_app_user_profiles WHERE user_id = %s",
                        (user_id,),
                    )
                    deleted = cur.rowcount > 0
                conn.commit()
                return deleted


_store: Optional[UserDataStore] = None
_store_lock = threading.Lock()


def get_user_data_store() -> UserDataStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is not None:
            return _store
        from plugins.app_gateway.config import load_app_gateway_config

        cfg = load_app_gateway_config()
        _store = UserDataStore(cfg.postgres_url)
        return _store


def reset_user_data_store_cache() -> None:
    """Test helper — drop cached store instance."""
    global _store
    with _store_lock:
        _store = None


def ensure_user_profile(user_id: str) -> Dict[str, Any]:
    return get_user_data_store().ensure_profile(user_id)


def save_user_profile(
    user_id: str,
    *,
    config: Dict[str, Any],
    env_secrets: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_user_data_store().save_profile(
        user_id,
        config=config,
        env_secrets=env_secrets,
    )


def hydrate_user_profile_to_home(user_id: str, home) -> None:
    """Legacy no-op — DB users use in-memory config overrides instead of files."""
    logger.debug(
        "hydrate_user_profile_to_home skipped for %s (in-memory DB config scope)",
        user_id,
    )


def load_user_profile_env(user_id: str) -> Dict[str, str]:
    profile = ensure_user_profile(user_id)
    env = profile.get("env_secrets") or {}
    return {str(k): str(v) for k, v in env.items() if str(k).strip()}


def load_user_profile_config(user_id: str) -> Dict[str, Any]:
    profile = ensure_user_profile(user_id)
    cfg = profile.get("config")
    return dict(cfg) if isinstance(cfg, dict) else copy.deepcopy(_DEFAULT_USER_CONFIG)
