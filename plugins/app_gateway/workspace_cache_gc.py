"""TTL and size limits for MinIO ``workspace-cache`` directories."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

_LAST_PRUNE_AT: Dict[str, float] = {}


def _cache_gc_settings() -> tuple[bool, float, float, int]:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        cfg = load_app_gateway_config()
        enabled = bool(getattr(cfg, "workspace_cache_gc_enabled", True))
        ttl_hours = float(getattr(cfg, "workspace_cache_ttl_hours", 72) or 0)
        max_mb = float(getattr(cfg, "workspace_cache_max_mb", 256) or 0)
        interval = int(getattr(cfg, "workspace_cache_gc_interval_seconds", 300) or 300)
        return enabled, ttl_hours, max_mb, max(60, interval)
    except Exception:
        return True, 72.0, 256.0, 300


def _pending_paths(user_id: str) -> Set[str]:
    try:
        from plugins.app_gateway.workspace_upload_queue import get_workspace_upload_queue

        return get_workspace_upload_queue().pending_relative_paths(user_id)
    except Exception:
        return set()


def _iter_cache_files(root: Path):
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "README.md" and path.parent == root:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        yield path, rel, stat.st_mtime, stat.st_size


def prune_workspace_cache(
    user_id: str,
    *,
    ttl_hours: float = 0,
    max_mb: float = 0,
) -> Dict[str, Any]:
    """Remove stale or excess files from a user's local workspace cache."""
    from plugins.app_gateway.workspace_backend import get_workspace_backend, use_minio_workspace

    if not use_minio_workspace():
        return {"files_removed": 0, "bytes_removed": 0}

    backend = get_workspace_backend()
    root = backend.local_root(user_id)
    pending = _pending_paths(user_id)
    cutoff = time.time() - float(ttl_hours or 0) * 3600 if float(ttl_hours or 0) > 0 else None
    max_bytes = int(float(max_mb or 0) * 1024 * 1024) if float(max_mb or 0) > 0 else 0

    removed = 0
    bytes_removed = 0
    survivors = []

    for path, rel, mtime, size in _iter_cache_files(root):
        if rel in pending:
            survivors.append((path, rel, mtime, size))
            continue
        if cutoff is not None and mtime < cutoff:
            try:
                path.unlink()
                removed += 1
                bytes_removed += size
            except OSError:
                pass
            continue
        survivors.append((path, rel, mtime, size))

    if max_bytes > 0:
        total = sum(size for _, _, _, size in survivors)
        survivors.sort(key=lambda item: item[2])
        while survivors and total > max_bytes:
            path, rel, mtime, size = survivors.pop(0)
            if rel in pending:
                total -= size
                continue
            try:
                path.unlink()
                removed += 1
                bytes_removed += size
                total -= size
            except OSError:
                total -= size

    uploads_root = root / "uploads"
    if uploads_root.is_dir():
        for path in sorted(uploads_root.rglob("*"), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

    return {"files_removed": removed, "bytes_removed": bytes_removed}


def maybe_prune_workspace_cache(user_id: str) -> Dict[str, Any] | None:
    """Throttled cache prune invoked at the start of a user scope."""
    enabled, ttl_hours, max_mb, interval = _cache_gc_settings()
    if not enabled:
        return None
    if float(ttl_hours or 0) <= 0 and float(max_mb or 0) <= 0:
        return None

    now = time.time()
    last = _LAST_PRUNE_AT.get(user_id, 0.0)
    if now - last < interval:
        return None
    _LAST_PRUNE_AT[user_id] = now
    try:
        return prune_workspace_cache(user_id, ttl_hours=ttl_hours, max_mb=max_mb)
    except Exception as exc:
        logger.debug("workspace cache prune skipped for %s: %s", user_id, exc)
        return None


def reset_workspace_cache_gc_state() -> None:
    _LAST_PRUNE_AT.clear()
