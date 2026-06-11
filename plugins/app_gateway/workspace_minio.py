"""MinIO-backed workspace storage with a local write-through cache."""

from __future__ import annotations

import fnmatch
import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from plugins.app_gateway.user_scope import operator_app_gateway_root, sanitize_user_id
from plugins.app_gateway.workspace_backend import WorkspaceObject

logger = logging.getLogger(__name__)

_CLIENT = None
_CLIENT_LOCK = threading.RLock()
_BUCKET_READY = False


@dataclass(frozen=True)
class MinioSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool
    prefix: str


def load_minio_settings() -> MinioSettings:
    import os

    from plugins.app_gateway.config import load_app_gateway_config

    cfg = load_app_gateway_config()
    return MinioSettings(
        endpoint=(
            os.environ.get("APP_GATEWAY_MINIO_ENDPOINT", "").strip()
            or str(getattr(cfg, "minio_endpoint", "") or "127.0.0.1:9000").strip()
        ),
        access_key=(
            os.environ.get("APP_GATEWAY_MINIO_ACCESS_KEY", "").strip()
            or str(getattr(cfg, "minio_access_key", "") or "minioadmin").strip()
        ),
        secret_key=(
            os.environ.get("APP_GATEWAY_MINIO_SECRET_KEY", "").strip()
            or str(getattr(cfg, "minio_secret_key", "") or "minioadmin").strip()
        ),
        bucket=str(getattr(cfg, "minio_bucket") or "hermes-workspaces").strip(),
        secure=bool(getattr(cfg, "minio_secure", False)),
        prefix=str(getattr(cfg, "minio_prefix") or "workspaces").strip("/"),
    )


def _get_client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError(
                "minio package is required for workspace_backend=minio "
                "(pip install 'hermes-agent[postgres]')"
            ) from exc
        settings = load_minio_settings()
        _CLIENT = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        return _CLIENT


def _ensure_bucket() -> None:
    global _BUCKET_READY
    if _BUCKET_READY:
        return
    with _CLIENT_LOCK:
        if _BUCKET_READY:
            return
        settings = load_minio_settings()
        client = _get_client()
        if not client.bucket_exists(settings.bucket):
            client.make_bucket(settings.bucket)
        _BUCKET_READY = True


def _object_key(user_id: str, relative_path: str) -> str:
    settings = load_minio_settings()
    safe = sanitize_user_id(user_id)
    rel = relative_path.replace("\\", "/").lstrip("/")
    return f"{settings.prefix}/{safe}/{rel}"


def upload_remote_bytes(user_id: str, relative_path: str, data: bytes) -> None:
    """Upload bytes to MinIO without touching the local cache."""
    rel = MinioWorkspaceBackend().normalize_relative_path(relative_path)
    _ensure_bucket()
    settings = load_minio_settings()
    client = _get_client()
    client.put_object(
        settings.bucket,
        _object_key(user_id, rel),
        io.BytesIO(data),
        length=len(data),
    )


def _fetch_remote_bytes(user_id: str, relative_path: str) -> Optional[bytes]:
    rel = relative_path.replace("\\", "/").lstrip("/")
    _ensure_bucket()
    settings = load_minio_settings()
    client = _get_client()
    key = _object_key(user_id, rel)
    try:
        response = client.get_object(settings.bucket, key)
    except Exception as exc:
        from minio.error import S3Error

        if isinstance(exc, S3Error) and exc.code in {"NoSuchKey", "NoSuchObject"}:
            return None
        logger.debug("MinIO get_object failed for %s: %s", key, exc)
        return None
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _search_prefetch_limit() -> int:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        return max(10, int(getattr(load_app_gateway_config(), "workspace_search_prefetch_max_files", 100) or 100))
    except Exception:
        return 100


def _matches_file_glob(relative_path: str, file_glob: Optional[str]) -> bool:
    if not file_glob:
        return True
    name = Path(relative_path).name
    return fnmatch.fnmatch(name, file_glob) or fnmatch.fnmatch(relative_path, file_glob)


def _matches_files_pattern(relative_path: str, pattern: str) -> bool:
    base = Path(relative_path).name
    raw = (pattern or "").strip()
    if not raw:
        return True
    if raw.startswith("**/"):
        return fnmatch.fnmatch(relative_path, raw) or fnmatch.fnmatch(base, raw[3:])
    if "/" not in raw:
        return fnmatch.fnmatch(base, raw) or fnmatch.fnmatch(relative_path, f"**/{raw}")
    return fnmatch.fnmatch(relative_path, raw) or fnmatch.fnmatch(base, raw.split("/")[-1])

class MinioWorkspaceBackend:
    def backend_name(self) -> str:
        return "minio"

    def local_root(self, user_id: str) -> Path:
        safe = sanitize_user_id(user_id)
        root = operator_app_gateway_root() / "workspace-cache" / safe
        root.mkdir(parents=True, exist_ok=True)
        return root

    def normalize_relative_path(self, rel: str) -> str:
        from pathlib import PurePosixPath

        cleaned = str(rel or "").strip().replace("\\", "/").lstrip("/")
        if not cleaned:
            raise ValueError("path is required")
        parts = PurePosixPath(cleaned).parts
        if ".." in parts:
            raise ValueError("invalid path")
        return cleaned

    def write_local_bytes(self, user_id: str, relative_path: str, data: bytes) -> Path:
        rel = self.normalize_relative_path(relative_path)
        local = self.local_root(user_id) / Path(rel)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return local

    def put_bytes(self, user_id: str, relative_path: str, data: bytes) -> None:
        rel = self.normalize_relative_path(relative_path)
        self.write_local_bytes(user_id, rel, data)
        from plugins.app_gateway.workspace_upload_queue import enqueue_workspace_upload

        enqueue_workspace_upload(user_id, rel, data=data)

    def get_bytes(self, user_id: str, relative_path: str) -> Optional[bytes]:
        rel = self.normalize_relative_path(relative_path)
        local = self.local_root(user_id) / Path(rel)
        if local.is_file():
            return local.read_bytes()
        data = _fetch_remote_bytes(user_id, rel)
        if data is None:
            return None
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return data

    def delete_object(self, user_id: str, relative_path: str) -> bool:
        rel = self.normalize_relative_path(relative_path)
        _ensure_bucket()
        settings = load_minio_settings()
        client = _get_client()
        key = _object_key(user_id, rel)
        try:
            client.remove_object(settings.bucket, key)
        except Exception as exc:
            logger.debug("MinIO remove_object failed for %s: %s", key, exc)
            return False
        local = self.local_root(user_id) / Path(rel)
        if local.is_file():
            local.unlink()
        return True

    def list_objects(self, user_id: str, *, prefix: str = "") -> List[WorkspaceObject]:
        _ensure_bucket()
        settings = load_minio_settings()
        client = _get_client()
        base_prefix = f"{settings.prefix}/{sanitize_user_id(user_id)}/"
        search_prefix = base_prefix
        if prefix and prefix not in (".", ""):
            rel = self.normalize_relative_path(prefix).rstrip("/")
            search_prefix = f"{base_prefix}{rel}/" if rel else base_prefix

        out: List[WorkspaceObject] = []
        for item in client.list_objects(settings.bucket, prefix=search_prefix, recursive=True):
            key = item.object_name or ""
            if not key.startswith(base_prefix):
                continue
            rel = key[len(base_prefix) :].lstrip("/")
            if not rel or rel.endswith("/"):
                continue
            out.append(
                WorkspaceObject(
                    relative_path=rel,
                    size=int(item.size or 0),
                    last_modified=float(item.last_modified.timestamp()) if item.last_modified else 0.0,
                )
            )
        return out

    def ensure_local_file(self, user_id: str, relative_path: str) -> Path:
        rel = self.normalize_relative_path(relative_path)
        local = self.local_root(user_id) / Path(rel)
        if local.is_file():
            return local
        data = self.get_bytes(user_id, rel)
        if data is None:
            raise FileNotFoundError(rel)
        return local

    def sync_local_path(self, user_id: str, resolved: Path) -> None:
        root = self.local_root(user_id)
        try:
            rel = resolved.resolve().relative_to(root.resolve())
        except ValueError:
            return
        if not resolved.is_file():
            return
        rel_str = str(rel).replace("\\", "/")
        from plugins.app_gateway.workspace_upload_queue import enqueue_workspace_upload

        enqueue_workspace_upload(user_id, rel_str, local_path=resolved)

    def prefetch_prefix(self, user_id: str, *, prefix: str = "") -> int:
        count = 0
        for obj in self.list_objects(user_id, prefix=prefix):
            if obj.relative_path == "README.md":
                continue
            local = self.local_root(user_id) / Path(obj.relative_path)
            if local.is_file():
                continue
            data = self.get_bytes(user_id, obj.relative_path)
            if data is None:
                continue
            count += 1
        return count

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
        """Hydrate only search-relevant objects instead of the whole prefix."""
        prefix = (path or ".").strip()
        if prefix in {".", ""}:
            prefix = ""
        else:
            prefix = self.normalize_relative_path(prefix).rstrip("/")

        objects = self.list_objects(user_id, prefix=prefix)
        candidates: List[WorkspaceObject] = []
        for obj in objects:
            if obj.relative_path == "README.md":
                continue
            if target == "files":
                if not _matches_files_pattern(obj.relative_path, pattern):
                    continue
            else:
                if not _matches_file_glob(obj.relative_path, file_glob):
                    continue
            candidates.append(obj)

        count = 0
        if target == "files":
            for obj in candidates[offset : offset + max(1, int(limit or 50))]:
                local = self.local_root(user_id) / Path(obj.relative_path)
                if local.is_file():
                    continue
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(b"")
                count += 1
            return count

        max_files = min(len(candidates), _search_prefetch_limit(), max(1, int(offset or 0) + int(limit or 50) + 20))
        for obj in candidates[:max_files]:
            local = self.local_root(user_id) / Path(obj.relative_path)
            if local.is_file():
                continue
            data = _fetch_remote_bytes(user_id, obj.relative_path)
            if data is None:
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
            count += 1
        return count
