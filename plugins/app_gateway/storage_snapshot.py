"""MinIO-aware storage usage for ``/v1/me/storage``."""

from __future__ import annotations

from typing import Any, Dict

from plugins.app_gateway.user_scope import ensure_user_home
from plugins.app_gateway.workspace_backend import use_minio_workspace
from plugins.app_gateway.workspace_storage import (
    local_workspace_usage_snapshot,
    workspace_usage_snapshot,
)


def _upload_queue_meta(user_id: str) -> Dict[str, int]:
    try:
        from plugins.app_gateway.workspace_upload_queue import get_workspace_upload_queue

        queue = get_workspace_upload_queue()
        return {
            "pending_uploads": len(queue.pending_relative_paths(user_id)),
            "failed_uploads": len(queue.failed_relative_paths(user_id)),
        }
    except Exception:
        return {"pending_uploads": 0, "failed_uploads": 0}


def storage_usage_snapshot(user_id: str) -> Dict[str, Any]:
    """Authoritative remote usage when MinIO is enabled, plus cache/queue metadata."""
    ensure_user_home(user_id, include_global_skills=False)
    local = local_workspace_usage_snapshot(user_id)
    queue_meta = _upload_queue_meta(user_id)

    if not use_minio_workspace():
        return {**local, **queue_meta}

    try:
        remote = workspace_usage_snapshot(user_id)
    except Exception:
        remote = {k: local[k] for k in ("bytes_used", "file_count", "uploads_bytes", "uploads_count", "backend")}

    return {
        **remote,
        "source": "remote",
        "local_cache_bytes": int(local.get("bytes_used") or 0),
        "local_cache_files": int(local.get("file_count") or 0),
        **queue_meta,
    }
