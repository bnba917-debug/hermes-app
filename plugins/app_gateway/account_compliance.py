"""Account compliance helpers for App Gateway (legal docs, internal cleanup)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.user_scope import operator_hermes_root, user_hermes_home

logger = logging.getLogger(__name__)


def _shared_session_db():
    from hermes_state import get_shared_session_db

    return get_shared_session_db()


def _app_gateway_session_rows(user_id: str, *, limit: int = 500) -> List[dict]:
    from plugins.app_gateway.session_keys import _session_token

    db = _shared_session_db()
    prefix = f"app_{_session_token(user_id)}_"
    rows = db.list_sessions_rich(
        source="app_gateway",
        limit=max(limit * 4, limit),
        offset=0,
        include_children=True,
        order_by_last_active=True,
    )
    owned: List[dict] = []
    for row in rows:
        if str(row.get("user_id") or "") == user_id or str(row.get("id") or "").startswith(prefix):
            owned.append(row)
        if len(owned) >= limit:
            break
    return owned


def _delete_app_gateway_sessions(user_id: str) -> int:
    """Remove Hermes sessions/messages for this app user (SQLite or Postgres)."""
    db = _shared_session_db()
    removed = 0
    for row in _app_gateway_session_rows(user_id, limit=10_000):
        sid = str(row.get("id") or "")
        if not sid:
            continue
        try:
            if db.delete_session(sid):
                removed += 1
        except Exception as exc:
            logger.debug("delete_session failed for %s: %s", sid, exc)
    return removed


def _remove_user_home(home: Path) -> bool:
    """Remove per-user home directory; return True only if the tree is gone."""
    if not home.is_dir():
        return False
    try:
        shutil.rmtree(home)
    except OSError as exc:
        logger.warning("failed to remove user home %s: %s", home, exc)
        return False
    return not home.exists()


def _delete_user_profile(user_id: str) -> bool:
    """Erase PostgreSQL profile + env secrets when user data store is enabled."""
    try:
        from plugins.app_gateway.user_data_store import (
            get_user_data_store,
            use_postgres_user_data,
        )

        if not use_postgres_user_data():
            return False
        return get_user_data_store().delete_profile(user_id)
    except Exception as exc:
        logger.warning("delete_profile failed for %s: %s", user_id, exc)
        return False


def _user_workspace_cache_dir(user_id: str) -> Path:
    from plugins.app_gateway.user_scope import operator_app_gateway_root, sanitize_user_id

    return operator_app_gateway_root() / "workspace-cache" / sanitize_user_id(user_id)


def _delete_user_workspace(user_id: str) -> Dict[str, Any]:
    """Remove MinIO workspace objects and local ``workspace-cache/<user_id>/``."""
    remote_removed = 0
    try:
        from plugins.app_gateway.workspace_backend import get_workspace_backend, use_minio_workspace

        if use_minio_workspace():
            backend = get_workspace_backend()
            for obj in backend.list_objects(user_id):
                if backend.delete_object(user_id, obj.relative_path):
                    remote_removed += 1
    except Exception as exc:
        logger.debug("remote workspace cleanup failed for %s: %s", user_id, exc)
    cache_removed = _remove_user_home(_user_workspace_cache_dir(user_id))
    return {
        "remote_objects_removed": remote_removed,
        "workspace_cache_removed": cache_removed,
    }


def verify_delete_account_code(
    user_id: str,
    code: str,
    config: Any,
) -> None:
    """Verify SMS OTP before destructive account deletion."""
    if not bool(getattr(config, "delete_account_sms_verify", True)):
        return
    from plugins.app_gateway.user_registry import get_user_registry

    submitted = str(code or "").strip()
    if not submitted:
        raise ValueError("SMS verification code is required")

    registry = get_user_registry()
    record = registry.get_by_user_id(user_id)
    if record is None:
        raise ValueError("user not found")

    ok = registry.verify_otp(record.phone, submitted)
    if not ok:
        raise ValueError("invalid or expired verification code")


def send_delete_account_sms(user_id: str, config: Any) -> Dict[str, Any]:
    """Send OTP to the user's registered phone for account deletion."""
    from plugins.app_gateway.phone_auth import mask_phone, send_sms_code
    from plugins.app_gateway.user_registry import get_user_registry

    record = get_user_registry().get_by_user_id(user_id)
    if record is None:
        raise ValueError("user not found")
    payload = send_sms_code(config, record.phone)
    payload["phone"] = mask_phone(record.phone)
    payload["purpose"] = "account_delete"
    return payload


def delete_user_account(
    ctx: UserContext,
    *,
    vector_memory: Any = None,
    audit: Any = None,
) -> Dict[str, Any]:
    """Erase user registry row, home directory, sessions, and vector memory."""
    from plugins.app_gateway.run_registry import cancel_runs_for_user
    from plugins.app_gateway.user_registry import get_user_registry

    uid = ctx.user_id
    cancel_runs_for_user(uid)
    sessions_removed = _delete_app_gateway_sessions(uid)
    if vector_memory is not None and hasattr(vector_memory, "delete_user"):
        vector_memory.delete_user(uid)
    workspace_cleanup = _delete_user_workspace(uid)
    home = user_hermes_home(uid)
    home_removed = _remove_user_home(home)
    profile_deleted = _delete_user_profile(uid)
    registry = get_user_registry()
    registry_deleted = False
    if hasattr(registry, "delete_user"):
        registry_deleted = registry.delete_user(uid)
    if audit is not None:
        try:
            audit.log(
                user_id=uid,
                session_id=ctx.session_id,
                event_type="account.deleted",
                payload={
                    "sessions_removed": sessions_removed,
                    "home_removed": home_removed,
                    "profile_deleted": profile_deleted,
                    "workspace_cache_removed": workspace_cleanup.get("workspace_cache_removed"),
                    "remote_objects_removed": workspace_cleanup.get("remote_objects_removed"),
                },
            )
        except Exception as exc:
            logger.debug("audit log on delete failed: %s", exc)
    return {
        "ok": True,
        "user_id": uid,
        "sessions_removed": sessions_removed,
        "home_removed": home_removed,
        "profile_deleted": profile_deleted,
        "workspace_cache_removed": workspace_cleanup.get("workspace_cache_removed", False),
        "remote_objects_removed": workspace_cleanup.get("remote_objects_removed", 0),
        "registry_deleted": registry_deleted,
    }


def legal_document_path(name: str) -> Optional[Path]:
    """Resolve legal markdown (bundled plugin copy, then operator override)."""
    safe = name.replace("..", "").strip("/\\")
    if safe not in ("terms", "privacy", "data-retention"):
        return None
    bundled = Path(__file__).resolve().parent / "legal" / f"{safe}.md"
    if bundled.is_file():
        return bundled
    override = operator_hermes_root() / "app_gateway" / "legal" / f"{safe}.md"
    return override if override.is_file() else None
