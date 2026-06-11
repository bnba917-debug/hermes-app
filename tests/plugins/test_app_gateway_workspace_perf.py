"""Performance optimizations for MinIO workspace storage."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.workspace_backend import (
    get_workspace_backend,
    reset_workspace_backend_cache,
)
from plugins.app_gateway.workspace_cache_gc import (
    prune_workspace_cache,
    reset_workspace_cache_gc_state,
)
from plugins.app_gateway.workspace_upload_queue import (
    reset_workspace_upload_queue,
    wait_for_workspace_uploads,
)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_workspace_backend_cache()
    reset_workspace_upload_queue()
    reset_workspace_cache_gc_state()
    yield
    reset_workspace_backend_cache()
    reset_workspace_upload_queue()
    reset_workspace_cache_gc_state()


@pytest.fixture
def gateway_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _enable_minio(monkeypatch, **overrides):
    cfg = AppGatewayConfig(workspace_backend="minio", **overrides)
    monkeypatch.setattr(
        "plugins.app_gateway.config.load_app_gateway_config",
        lambda: cfg,
    )


def _fake_get(store, key):
    if key not in store:
        from minio.error import S3Error

        raise S3Error("NoSuchKey", "NoSuchKey", "missing", "GET", "/", None, None)
    resp = MagicMock()
    resp.read.return_value = store[key]
    return resp


def test_async_upload_defers_minio_put(gateway_home, monkeypatch):
    import threading

    _enable_minio(monkeypatch, workspace_minio_async_upload=True)
    store: dict[str, bytes] = {}
    upload_started = threading.Event()
    allow_upload = threading.Event()

    def _delayed_put(bucket, key, stream, length):
        upload_started.set()
        allow_upload.wait(timeout=1.0)
        store[key] = stream.read()

    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True
    fake_client.put_object.side_effect = _delayed_put
    fake_client.list_objects.return_value = []

    with patch("plugins.app_gateway.workspace_minio._get_client", return_value=fake_client):
        backend = get_workspace_backend()
        backend.put_bytes("alice", "notes/a.txt", b"hello")
        assert (backend.local_root("alice") / "notes/a.txt").read_bytes() == b"hello"
        assert store == {}
        assert upload_started.wait(timeout=1.0)
        allow_upload.set()
        assert wait_for_workspace_uploads(timeout=2.0)
        assert any(store[k] == b"hello" for k in store)


def test_search_prefetch_downloads_only_matching_content_files(gateway_home, monkeypatch):
    _enable_minio(monkeypatch)
    store = {
        "workspaces/alice/a.py": b"print('a')",
        "workspaces/alice/b.txt": b"hello",
        "workspaces/alice/c.py": b"print('c')",
    }

    class ListedObject:
        def __init__(self, key: str, data: bytes):
            self.object_name = key
            self.size = len(data)

        @property
        def last_modified(self):
            from datetime import datetime, timezone

            return datetime.now(timezone.utc)

    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True
    fake_client.get_object.side_effect = lambda bucket, key: _fake_get(store, key)
    fake_client.list_objects.side_effect = lambda bucket, prefix="", recursive=False: (
        ListedObject(k, v) for k, v in store.items() if k.startswith(prefix)
    )

    with patch("plugins.app_gateway.workspace_minio._get_client", return_value=fake_client):
        backend = get_workspace_backend()
        fetched = backend.prefetch_for_search(
            "alice",
            target="content",
            pattern="print",
            file_glob="*.py",
            limit=10,
            offset=0,
        )
        root = backend.local_root("alice")
        assert fetched == 2
        assert (root / "c.py").is_file()
        assert not (root / "b.txt").exists()


def test_search_prefetch_files_target_creates_stubs_only(gateway_home, monkeypatch):
    _enable_minio(monkeypatch)
    store = {
        "workspaces/alice/docs/readme.md": b"# doc",
        "workspaces/alice/src/main.py": b"print(1)",
    }

    class ListedObject:
        def __init__(self, key: str, data: bytes):
            self.object_name = key
            self.size = len(data)

        @property
        def last_modified(self):
            from datetime import datetime, timezone

            return datetime.now(timezone.utc)

    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True
    fake_client.get_object.side_effect = lambda bucket, key: _fake_get(store, key)
    fake_client.list_objects.side_effect = lambda bucket, prefix="", recursive=False: (
        ListedObject(k, v) for k, v in store.items() if k.startswith(prefix)
    )

    with patch("plugins.app_gateway.workspace_minio._get_client", return_value=fake_client):
        backend = get_workspace_backend()
        fetched = backend.prefetch_for_search(
            "alice",
            target="files",
            pattern="*.py",
            limit=10,
            offset=0,
        )
        root = backend.local_root("alice")
        assert fetched == 1
        assert (root / "src/main.py").is_file()
        assert (root / "src/main.py").read_bytes() == b""
        assert not (root / "docs/readme.md").exists()


def test_workspace_cache_prune_respects_ttl_and_pending(gateway_home, monkeypatch):
    _enable_minio(monkeypatch, workspace_cache_ttl_hours=1, workspace_cache_max_mb=0)
    backend = get_workspace_backend()
    root = backend.local_root("alice")
    old = root / "old.txt"
    fresh = root / "fresh.txt"
    pending = root / "pending.txt"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    pending.write_bytes(b"pending")
    old_time = time.time() - 7200
    import os

    os.utime(old, (old_time, old_time))

    from plugins.app_gateway.workspace_upload_queue import get_workspace_upload_queue

    queue = get_workspace_upload_queue()
    with queue._lock:
        queue._pending.add(("alice", "pending.txt"))

    result = prune_workspace_cache("alice", ttl_hours=1, max_mb=0)

    assert result["files_removed"] == 1
    assert not old.exists()
    assert fresh.exists()
    assert pending.exists()
