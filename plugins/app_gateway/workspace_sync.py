"""Bridge Hermes file tools and App Gateway workspace backends."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _session_user_id() -> str:
    try:
        from gateway.session_context import get_session_env

        return str(get_session_env("HERMES_SESSION_USER_ID") or "").strip()
    except Exception:
        return ""


def workspace_sync_active() -> bool:
    try:
        from tools.file_tools import _is_app_gateway_file_session

        from plugins.app_gateway.workspace_backend import use_minio_workspace

        return bool(_is_app_gateway_file_session() and use_minio_workspace())
    except Exception:
        return False


def prefetch_workspace_file(relative_path: str, task_id: str = "default") -> bool:
    """Download a single object into the local cache when missing."""
    if not workspace_sync_active():
        return False
    user_id = _session_user_id()
    if not user_id:
        return False
    try:
        from plugins.app_gateway.workspace_backend import get_workspace_backend
        from plugins.app_gateway.workspace_paths import resolve_app_gateway_path

        backend = get_workspace_backend()
        resolved, err = resolve_app_gateway_path(relative_path, task_id=task_id)
        if err or resolved is None:
            return False
        if Path(resolved).is_file():
            return True
        root = backend.local_root(user_id)
        rel = str(resolved.resolve().relative_to(root.resolve())).replace("\\", "/")
        backend.ensure_local_file(user_id, rel)
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("prefetch_workspace_file failed: %s", exc)
        return False


def sync_workspace_relative_path(relative_path: str, task_id: str = "default") -> None:
    """Upload a locally written file to MinIO (async when enabled)."""
    if not workspace_sync_active():
        return
    user_id = _session_user_id()
    if not user_id:
        return
    try:
        from plugins.app_gateway.workspace_backend import get_workspace_backend
        from plugins.app_gateway.workspace_paths import resolve_app_gateway_path

        backend = get_workspace_backend()
        resolved, err = resolve_app_gateway_path(relative_path, task_id=task_id)
        if err or resolved is None or not Path(resolved).is_file():
            return
        backend.sync_local_path(user_id, Path(resolved))
    except Exception as exc:
        logger.debug("sync_workspace_relative_path failed: %s", exc)


def prefetch_workspace_search(
    path: str,
    task_id: str = "default",
    *,
    pattern: str = "",
    target: str = "content",
    file_glob: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> int:
    """Hydrate only search-relevant objects before ``search_files`` runs locally."""
    if not workspace_sync_active():
        return 0
    user_id = _session_user_id()
    if not user_id:
        return 0
    try:
        from plugins.app_gateway.workspace_backend import get_workspace_backend

        backend = get_workspace_backend()
        search_path = (path or ".").strip()
        if search_path not in {".", ""}:
            from plugins.app_gateway.workspace_paths import validate_workspace_relative_path

            err = validate_workspace_relative_path(search_path)
            if err:
                return 0
            search_path = search_path.replace("\\", "/").lstrip("/")
        else:
            search_path = "."

        prefetch = getattr(backend, "prefetch_for_search", None)
        if callable(prefetch):
            return int(
                prefetch(
                    user_id,
                    path=search_path,
                    target=target,
                    pattern=pattern,
                    file_glob=file_glob,
                    limit=limit,
                    offset=offset,
                )
                or 0
            )
        return backend.prefetch_prefix(user_id, prefix="" if search_path == "." else search_path)
    except Exception as exc:
        logger.debug("prefetch_workspace_search failed: %s", exc)
        return 0


def sync_workspace_bytes(user_id: str, relative_path: str, data: bytes) -> None:
    """Write-through helper for HTTP uploads and other non-file-tool writers."""
    if not user_id or not relative_path:
        return
    try:
        from plugins.app_gateway.workspace_backend import get_workspace_backend, use_minio_workspace
        from plugins.app_gateway.workspace_upload_queue import enqueue_workspace_upload

        if not use_minio_workspace():
            return
        backend = get_workspace_backend()
        local = backend.local_root(user_id) / Path(relative_path.replace("\\", "/"))
        if local.is_file():
            enqueue_workspace_upload(user_id, relative_path.replace("\\", "/"), local_path=local)
        else:
            backend.write_local_bytes(user_id, relative_path, data)
            enqueue_workspace_upload(user_id, relative_path.replace("\\", "/"), data=data)
    except Exception as exc:
        logger.debug("sync_workspace_bytes failed: %s", exc)
