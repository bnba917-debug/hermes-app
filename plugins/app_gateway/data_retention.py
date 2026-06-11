"""Scheduled data retention for App Gateway multi-tenant sessions and uploads."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.user_scope import operator_app_gateway_root, user_workspace

logger = logging.getLogger(__name__)

_STAMP_NAME = ".last_retention_run"


def _stamp_path() -> Path:
    return operator_app_gateway_root() / _STAMP_NAME


def _should_run(interval_hours: int) -> bool:
    path = _stamp_path()
    if not path.is_file():
        return True
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) >= max(1, interval_hours) * 3600


def _mark_run() -> None:
    path = _stamp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def _purge_user_uploads(user_id: str, cutoff_ts: float) -> int:
    removed = 0
    uploads_local = user_workspace(user_id) / "uploads"
    if uploads_local.is_dir():
        for path in uploads_local.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime >= cutoff_ts:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    try:
        from plugins.app_gateway.workspace_backend import get_workspace_backend

        backend = get_workspace_backend()
        for obj in backend.list_objects(user_id, prefix="uploads/"):
            if float(obj.last_modified) >= cutoff_ts:
                continue
            if backend.delete_object(user_id, obj.relative_path):
                removed += 1
    except Exception as exc:
        logger.debug("upload retention remote purge skipped for %s: %s", user_id, exc)
    return removed


def purge_stale_uploads(config: AppGatewayConfig) -> int:
    """Remove workspace ``uploads/`` files older than ``data_retention_days``."""
    days = int(getattr(config, "data_retention_days", 0) or 0)
    if days <= 0:
        return 0
    cutoff_ts = time.time() - days * 86400
    users_root = operator_app_gateway_root() / "users"
    if not users_root.is_dir():
        return 0
    removed = 0
    for user_dir in users_root.iterdir():
        if not user_dir.is_dir():
            continue
        removed += _purge_user_uploads(user_dir.name, cutoff_ts)
    if removed:
        logger.info(
            "App gateway upload retention: removed %d file(s) older than %d days",
            removed,
            days,
        )
    return removed


def run_data_retention(config: AppGatewayConfig) -> Dict[str, Any]:
    """Purge ended sessions and stale uploads older than ``data_retention_days``."""
    days = int(getattr(config, "data_retention_days", 0) or 0)
    if days <= 0:
        return {"skipped": True, "reason": "retention_disabled"}

    from hermes_state import get_shared_session_db

    db = get_shared_session_db()
    pruned = int(
        db.prune_sessions(
            older_than_days=days,
            source="app_gateway",
        )
        or 0
    )
    uploads_removed = purge_stale_uploads(config)
    logger.info(
        "App gateway data retention: pruned %d session(s), %d upload file(s) (> %d days)",
        pruned,
        uploads_removed,
        days,
    )
    return {
        "ok": True,
        "retention_days": days,
        "pruned_sessions": pruned,
        "uploads_removed": uploads_removed,
    }


def maybe_run_data_retention(config: AppGatewayConfig) -> Dict[str, Any]:
    """Idempotent retention sweep — at most once per ``data_retention_interval_hours``."""
    days = int(getattr(config, "data_retention_days", 0) or 0)
    if days <= 0:
        return {"skipped": True, "reason": "retention_disabled"}

    interval_hours = int(getattr(config, "data_retention_interval_hours", 24) or 24)
    if not _should_run(interval_hours):
        return {"skipped": True, "reason": "interval"}

    try:
        result = run_data_retention(config)
        _mark_run()
        return result
    except Exception as exc:
        logger.warning("App gateway data retention failed: %s", exc)
        return {"ok": False, "error": str(exc)}
