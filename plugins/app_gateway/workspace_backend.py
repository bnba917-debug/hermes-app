"""Workspace storage backends — local disk or MinIO (S3-compatible)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional, Protocol

logger = logging.getLogger(__name__)

_BACKEND: Optional["WorkspaceBackend"] = None
_BACKEND_LOCK = threading.Lock()


@dataclass(frozen=True)
class WorkspaceObject:
    relative_path: str
    size: int
    last_modified: float


class WorkspaceBackend(Protocol):
    def backend_name(self) -> str: ...

    def local_root(self, user_id: str) -> Path: ...

    def normalize_relative_path(self, rel: str) -> str: ...

    def put_bytes(self, user_id: str, relative_path: str, data: bytes) -> None: ...

    def get_bytes(self, user_id: str, relative_path: str) -> Optional[bytes]: ...

    def delete_object(self, user_id: str, relative_path: str) -> bool: ...

    def list_objects(self, user_id: str, *, prefix: str = "") -> List[WorkspaceObject]: ...

    def ensure_local_file(self, user_id: str, relative_path: str) -> Path: ...

    def sync_local_path(self, user_id: str, resolved: Path) -> None: ...

    def prefetch_prefix(self, user_id: str, *, prefix: str = "") -> int: ...

    def prefetch_for_search(
        self,
        user_id: str,
        *,
        path: str = ".",
        target: str = "content",
        pattern: str = "",
        file_glob: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> int: ...


def use_minio_workspace() -> bool:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        cfg = load_app_gateway_config()
        return str(getattr(cfg, "workspace_backend", "") or "").strip().lower() == "minio"
    except Exception:
        return False


def get_workspace_backend() -> WorkspaceBackend:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    with _BACKEND_LOCK:
        if _BACKEND is not None:
            return _BACKEND
        if use_minio_workspace():
            from plugins.app_gateway.workspace_minio import MinioWorkspaceBackend

            _BACKEND = MinioWorkspaceBackend()
        else:
            _BACKEND = LocalWorkspaceBackend()
        return _BACKEND


def reset_workspace_backend_cache() -> None:
    global _BACKEND
    with _BACKEND_LOCK:
        _BACKEND = None


class LocalWorkspaceBackend:
    """Legacy on-disk workspace under ``users/<id>/workspace/``."""

    def backend_name(self) -> str:
        return "local"

    def local_root(self, user_id: str) -> Path:
        from plugins.app_gateway.user_scope import user_hermes_home

        root = user_hermes_home(user_id) / "workspace"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def normalize_relative_path(self, rel: str) -> str:
        cleaned = str(rel or "").strip().replace("\\", "/").lstrip("/")
        if not cleaned:
            raise ValueError("path is required")
        parts = PurePosixPath(cleaned).parts
        if ".." in parts:
            raise ValueError("invalid path")
        return cleaned

    def put_bytes(self, user_id: str, relative_path: str, data: bytes) -> None:
        rel = self.normalize_relative_path(relative_path)
        dest = self.local_root(user_id) / Path(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def get_bytes(self, user_id: str, relative_path: str) -> Optional[bytes]:
        rel = self.normalize_relative_path(relative_path)
        dest = self.local_root(user_id) / Path(rel)
        if not dest.is_file():
            return None
        return dest.read_bytes()

    def delete_object(self, user_id: str, relative_path: str) -> bool:
        rel = self.normalize_relative_path(relative_path)
        dest = self.local_root(user_id) / Path(rel)
        if dest.is_file():
            dest.unlink()
            return True
        return False

    def list_objects(self, user_id: str, *, prefix: str = "") -> List[WorkspaceObject]:
        root = self.local_root(user_id)
        pref = ""
        if prefix and prefix not in (".", ""):
            pref = self.normalize_relative_path(prefix).rstrip("/")
        out: List[WorkspaceObject] = []
        if not root.is_dir():
            return out
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            if pref and not (rel == pref or rel.startswith(pref + "/")):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            out.append(
                WorkspaceObject(
                    relative_path=rel,
                    size=stat.st_size,
                    last_modified=stat.st_mtime,
                )
            )
        return out

    def ensure_local_file(self, user_id: str, relative_path: str) -> Path:
        rel = self.normalize_relative_path(relative_path)
        dest = self.local_root(user_id) / Path(rel)
        if not dest.is_file():
            raise FileNotFoundError(rel)
        return dest

    def sync_local_path(self, user_id: str, resolved: Path) -> None:
        return

    def prefetch_prefix(self, user_id: str, *, prefix: str = "") -> int:
        return 0

    def prefetch_for_search(
        self,
        user_id: str,
        *,
        path: str = ".",
        target: str = "content",
        pattern: str = "",
        file_glob: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> int:
        return 0
