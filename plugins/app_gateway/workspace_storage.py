"""Workspace usage and cleanup helpers for App Gateway users."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

from plugins.app_gateway.user_scope import ensure_user_home, user_workspace
from plugins.app_gateway.workspace_backend import get_workspace_backend


def _iter_workspace_objects(user_id: str):
    ensure_user_home(user_id, include_global_skills=False)
    backend = get_workspace_backend()
    for obj in backend.list_objects(user_id):
        if obj.relative_path == "README.md":
            continue
        yield obj


def _local_uploads_path(user_id: str) -> Path:
    return user_workspace(user_id) / "uploads"


def _local_workspace_usage(user_id: str) -> tuple[int, int, int, int]:
    """Scan the on-disk workspace cache only (fast; no remote I/O)."""
    ensure_user_home(user_id, include_global_skills=False)
    root = user_workspace(user_id)
    bytes_used = 0
    file_count = 0
    uploads_bytes = 0
    uploads_count = 0
    uploads_prefix = "uploads/"
    if not root.is_dir():
        return 0, 0, 0, 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "README.md" and path.parent == root:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        bytes_used += size
        file_count += 1
        if rel.startswith(uploads_prefix):
            uploads_bytes += size
            uploads_count += 1
    return bytes_used, file_count, uploads_bytes, uploads_count


def local_workspace_usage_snapshot(user_id: str) -> Dict[str, Any]:
    """Usage summary from the local cache — safe for upload hot paths."""
    bytes_used, file_count, uploads_bytes, uploads_count = _local_workspace_usage(user_id)
    backend = get_workspace_backend()
    return {
        "bytes_used": bytes_used,
        "file_count": file_count,
        "uploads_bytes": uploads_bytes,
        "uploads_count": uploads_count,
        "backend": backend.backend_name(),
        "source": "local",
    }


def workspace_usage_snapshot(user_id: str) -> Dict[str, Any]:
    """Return a small storage usage summary for the user's workspace."""
    bytes_used = 0
    file_count = 0
    uploads_bytes = 0
    uploads_count = 0
    uploads_prefix = "uploads/"

    for obj in _iter_workspace_objects(user_id):
        bytes_used += int(obj.size)
        file_count += 1
        if obj.relative_path.startswith(uploads_prefix):
            uploads_bytes += int(obj.size)
            uploads_count += 1

    backend = get_workspace_backend()
    return {
        "bytes_used": bytes_used,
        "file_count": file_count,
        "uploads_bytes": uploads_bytes,
        "uploads_count": uploads_count,
        "backend": backend.backend_name(),
    }


def clear_uploads(user_id: str) -> Dict[str, Any]:
    """Remove all upload files for a user; useful for manual cleanup flows."""
    ensure_user_home(user_id, include_global_skills=False)
    backend = get_workspace_backend()
    before = workspace_usage_snapshot(user_id)
    for obj in backend.list_objects(user_id, prefix="uploads"):
        backend.delete_object(user_id, obj.relative_path)
    uploads = _local_uploads_path(user_id)
    if uploads.is_dir():
        shutil.rmtree(uploads)
    after = workspace_usage_snapshot(user_id)
    return {
        "files_removed": max(0, int(before["file_count"]) - int(after["file_count"])),
        "bytes_removed": max(0, int(before["bytes_used"]) - int(after["bytes_used"])),
    }
