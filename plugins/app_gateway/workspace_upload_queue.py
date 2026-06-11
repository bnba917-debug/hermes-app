"""Background MinIO upload queue — local cache first, remote upload async with retries."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

UploadKey = Tuple[str, str]

_QUEUE: Optional["WorkspaceUploadQueue"] = None
_QUEUE_LOCK = threading.Lock()


def _async_upload_enabled() -> bool:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        return bool(getattr(load_app_gateway_config(), "workspace_minio_async_upload", True))
    except Exception:
        return True


def _max_upload_retries() -> int:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        return max(0, int(getattr(load_app_gateway_config(), "workspace_upload_max_retries", 3) or 3))
    except Exception:
        return 3


@dataclass
class _PendingJob:
    data: Optional[bytes] = None
    local_path: Optional[Path] = None
    attempts: int = 0


class WorkspaceUploadQueue:
    """Fire-and-forget uploads keyed by ``(user_id, relative_path)`` with retry."""

    def __init__(self, *, workers: int = 8) -> None:
        self._workers = max(1, int(workers or 8))
        self._executor = ThreadPoolExecutor(
            max_workers=self._workers,
            thread_name_prefix="ws-minio-upload",
        )
        self._pending: Set[UploadKey] = set()
        self._failed: Set[UploadKey] = set()
        self._jobs: Dict[UploadKey, _PendingJob] = {}
        self._lock = threading.Lock()
        self._total_failed = 0
        self._total_retried = 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "pending": len(self._pending),
                "failed": len(self._failed),
                "workers": self._workers,
                "total_failed": self._total_failed,
                "total_retried": self._total_retried,
            }

    def pending_relative_paths(self, user_id: str) -> Set[str]:
        with self._lock:
            return {rel for uid, rel in self._pending if uid == user_id}

    def failed_relative_paths(self, user_id: str) -> Set[str]:
        with self._lock:
            return {rel for uid, rel in self._failed if uid == user_id}

    def is_pending(self, user_id: str, relative_path: str) -> bool:
        with self._lock:
            return (user_id, relative_path) in self._pending

    def enqueue_bytes(self, user_id: str, relative_path: str, data: bytes) -> None:
        if not user_id or not relative_path:
            return
        key = (user_id, relative_path)
        with self._lock:
            self._pending.add(key)
            self._failed.discard(key)
            self._jobs[key] = _PendingJob(data=data)
        self._executor.submit(self._run_upload, key)

    def enqueue_local_path(self, user_id: str, relative_path: str, local_path: Path) -> None:
        if not user_id or not relative_path:
            return
        key = (user_id, relative_path)
        with self._lock:
            self._pending.add(key)
            self._failed.discard(key)
            self._jobs[key] = _PendingJob(local_path=Path(local_path))
        self._executor.submit(self._run_upload, key)

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + max(0.1, float(timeout or 0))
        while time.time() < deadline:
            with self._lock:
                if not self._pending:
                    return True
            time.sleep(0.01)
        with self._lock:
            return not self._pending

    def _schedule_retry(self, key: UploadKey, job: _PendingJob, exc: Exception) -> None:
        max_retries = _max_upload_retries()
        job.attempts += 1
        user_id, relative_path = key
        if job.attempts <= max_retries:
            delay = min(30.0, 2.0 ** job.attempts)
            logger.warning(
                "Async workspace upload failed for %s/%s (attempt %d/%d): %s — retry in %.1fs",
                user_id,
                relative_path,
                job.attempts,
                max_retries,
                exc,
                delay,
            )
            with self._lock:
                self._total_retried += 1

            def _retry() -> None:
                time.sleep(delay)
                with self._lock:
                    if key not in self._jobs:
                        return
                    self._pending.add(key)
                self._executor.submit(self._run_upload, key)

            threading.Thread(target=_retry, daemon=True, name="ws-minio-retry").start()
            return

        logger.error(
            "Async workspace upload permanently failed for %s/%s after %d attempts: %s",
            user_id,
            relative_path,
            job.attempts,
            exc,
        )
        with self._lock:
            self._pending.discard(key)
            self._failed.add(key)
            self._total_failed += 1
            self._jobs.pop(key, None)

    def _run_upload(self, key: UploadKey) -> None:
        user_id, relative_path = key
        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                self._pending.discard(key)
                return
        try:
            payload = job.data
            if payload is None:
                local_path = job.local_path
                if local_path is None or not local_path.is_file():
                    with self._lock:
                        self._pending.discard(key)
                        self._jobs.pop(key, None)
                    return
                payload = local_path.read_bytes()
            from plugins.app_gateway.workspace_minio import upload_remote_bytes

            upload_remote_bytes(user_id, relative_path, payload)
            with self._lock:
                self._pending.discard(key)
                self._failed.discard(key)
                self._jobs.pop(key, None)
        except Exception as exc:
            self._schedule_retry(key, job, exc)


def get_workspace_upload_queue() -> WorkspaceUploadQueue:
    global _QUEUE
    if _QUEUE is not None:
        return _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is not None:
            return _QUEUE
        try:
            from plugins.app_gateway.config import load_app_gateway_config

            workers = int(getattr(load_app_gateway_config(), "workspace_upload_workers", 8) or 8)
        except Exception:
            workers = 8
        _QUEUE = WorkspaceUploadQueue(workers=workers)
        return _QUEUE


def reset_workspace_upload_queue() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is not None:
            try:
                _QUEUE._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        _QUEUE = None


def wait_for_workspace_uploads(timeout: float = 5.0) -> bool:
    try:
        return get_workspace_upload_queue().wait_until_idle(timeout=timeout)
    except Exception:
        return True


def enqueue_workspace_upload(
    user_id: str,
    relative_path: str,
    *,
    data: Optional[bytes] = None,
    local_path: Optional[Path] = None,
    blocking: bool = False,
) -> None:
    """Queue or run a MinIO upload for one workspace object."""
    if not user_id or not relative_path:
        return
    if blocking or not _async_upload_enabled():
        payload = data
        if payload is None:
            if local_path is None or not Path(local_path).is_file():
                return
            payload = Path(local_path).read_bytes()
        from plugins.app_gateway.workspace_minio import upload_remote_bytes

        upload_remote_bytes(user_id, relative_path, payload)
        return
    queue = get_workspace_upload_queue()
    if data is not None:
        queue.enqueue_bytes(user_id, relative_path, data)
    elif local_path is not None:
        queue.enqueue_local_path(user_id, relative_path, Path(local_path))
