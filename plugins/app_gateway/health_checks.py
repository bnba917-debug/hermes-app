"""Optional deep dependency probes for App Gateway ``/health``."""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict

logger = logging.getLogger(__name__)


def probe_postgres(postgres_url: str) -> Dict[str, Any]:
    url = (postgres_url or "").strip()
    if not url:
        return {"ok": False, "configured": False}
    try:
        from agent.session_storage.postgres_pool import pool_for

        pool = pool_for(url)
        with pool.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"ok": True, "configured": True}
    except Exception as exc:
        logger.debug("postgres health probe failed: %s", exc)
        return {"ok": False, "configured": True, "error": str(exc)}


def probe_minio() -> Dict[str, Any]:
    try:
        from plugins.app_gateway.config import load_app_gateway_config
        from plugins.app_gateway.workspace_backend import use_minio_workspace

        if not use_minio_workspace():
            return {"ok": True, "configured": False, "backend": "local"}
        from plugins.app_gateway.workspace_minio import load_minio_settings

        settings = load_minio_settings()
        host, _, port = settings.endpoint.partition(":")
        port_i = int(port or ("443" if settings.secure else "9000"))
        with socket.create_connection((host, port_i), timeout=2.0):
            pass
        from plugins.app_gateway.workspace_minio import _ensure_bucket

        _ensure_bucket()
        return {"ok": True, "configured": True, "endpoint": settings.endpoint}
    except Exception as exc:
        logger.debug("minio health probe failed: %s", exc)
        return {"ok": False, "configured": True, "error": str(exc)}


def probe_upload_queue() -> Dict[str, Any]:
    try:
        from plugins.app_gateway.workspace_upload_queue import get_workspace_upload_queue

        return {"ok": True, **get_workspace_upload_queue().stats()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def probe_redis(redis_url: str) -> Dict[str, Any]:
    url = (redis_url or "").strip()
    if not url:
        return {"ok": False, "configured": False}
    try:
        import redis  # type: ignore

        client = redis.from_url(url, decode_responses=True)
        client.ping()
        return {"ok": True, "configured": True}
    except Exception as exc:
        logger.debug("redis health probe failed: %s", exc)
        return {"ok": False, "configured": True, "error": str(exc)}
