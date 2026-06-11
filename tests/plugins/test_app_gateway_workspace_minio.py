"""MinIO-backed App Gateway workspace storage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.workspace_backend import (
    LocalWorkspaceBackend,
    get_workspace_backend,
    reset_workspace_backend_cache,
)


@pytest.fixture(autouse=True)
def _reset_backend():
    reset_workspace_backend_cache()
    yield
    reset_workspace_backend_cache()


@pytest.fixture
def gateway_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _enable_minio(monkeypatch):
    monkeypatch.setenv("APP_GATEWAY_WORKSPACE_BACKEND", "")
    cfg = AppGatewayConfig(workspace_backend="minio", workspace_minio_async_upload=False)
    monkeypatch.setattr(
        "plugins.app_gateway.config.load_app_gateway_config",
        lambda: cfg,
    )


def test_user_workspace_uses_cache_dir_when_minio_enabled(gateway_home, monkeypatch):
    _enable_minio(monkeypatch)
    from plugins.app_gateway.user_scope import ensure_user_home, user_workspace

    ensure_user_home("alice", include_global_skills=False)
    ws = user_workspace("alice")
    assert ws.is_dir()
    assert ws == gateway_home / "app_gateway" / "workspace-cache" / "alice"
    assert (ws / "README.md").is_file()


def _fake_get(store, key):
    if key not in store:
        from minio.error import S3Error

        raise S3Error("NoSuchKey", "NoSuchKey", "missing", "GET", "/", None, None)
    resp = MagicMock()
    resp.read.return_value = store[key]
    return resp


def test_minio_backend_put_and_list(gateway_home, monkeypatch):
    _enable_minio(monkeypatch)
    store: dict[str, bytes] = {}

    class FakeObject:
        def __init__(self, key: str, data: bytes):
            self.object_name = key
            self.size = len(data)

        @property
        def last_modified(self):
            from datetime import datetime, timezone

            return datetime.now(timezone.utc)

    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True

    def _put(bucket, key, stream, length):
        store[key] = stream.read()

    def _list(bucket, prefix="", recursive=False):
        for key, data in store.items():
            if key.startswith(prefix):
                yield FakeObject(key, data)

    fake_client.put_object.side_effect = _put
    fake_client.get_object.side_effect = lambda bucket, key: _fake_get(store, key)
    fake_client.list_objects.side_effect = _list

    with patch("plugins.app_gateway.workspace_minio._get_client", return_value=fake_client):
        backend = get_workspace_backend()
        assert backend.backend_name() == "minio"
        backend.put_bytes("alice", "notes/a.txt", b"hello")
        objs = backend.list_objects("alice")
        assert len(objs) == 1
        assert objs[0].relative_path == "notes/a.txt"
        assert backend.get_bytes("alice", "notes/a.txt") == b"hello"


def test_chat_attachment_syncs_to_minio(gateway_home, monkeypatch):
    _enable_minio(monkeypatch)
    store: dict[str, bytes] = {}
    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True
    fake_client.put_object.side_effect = lambda bucket, key, stream, length: store.update(
        {key: stream.read()}
    )
    fake_client.list_objects.return_value = []

    ctx = UserContext(user_id="bob", session_id="s1", device_id=None, raw_claims={})
    with patch("plugins.app_gateway.workspace_minio._get_client", return_value=fake_client):
        from plugins.app_gateway.chat_attachments import store_chat_attachment

        result = store_chat_attachment(ctx, file_bytes=b"payload", filename="doc.txt")
        assert result["ok"] is True
        assert any(key.endswith("/uploads/") or "/uploads/" in key for key in store)
        assert any(store[k] == b"payload" for k in store)


def test_local_backend_when_not_minio(gateway_home, monkeypatch):
    cfg = AppGatewayConfig(workspace_backend="local")
    monkeypatch.setattr(
        "plugins.app_gateway.config.load_app_gateway_config",
        lambda: cfg,
    )
    backend = get_workspace_backend()
    assert isinstance(backend, LocalWorkspaceBackend)
    backend.put_bytes("alice", "x.txt", b"1")
    assert (backend.local_root("alice") / "x.txt").read_bytes() == b"1"


def test_workspace_usage_snapshot_reports_minio_backend(gateway_home, monkeypatch):
    _enable_minio(monkeypatch)
    store: dict[str, bytes] = {}

    class FakeObject:
        def __init__(self, key: str, data: bytes):
            self.object_name = key
            self.size = len(data)

        @property
        def last_modified(self):
            from datetime import datetime, timezone

            return datetime.now(timezone.utc)

    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True
    fake_client.put_object.side_effect = lambda bucket, key, stream, length: store.update(
        {key: stream.read()}
    )
    fake_client.get_object.side_effect = lambda bucket, key: _fake_get(store, key)
    fake_client.list_objects.side_effect = lambda bucket, prefix="", recursive=False: (
        FakeObject(k, v) for k, v in store.items() if k.startswith(prefix)
    )

    with patch("plugins.app_gateway.workspace_minio._get_client", return_value=fake_client):
        from plugins.app_gateway.workspace_storage import workspace_usage_snapshot

        backend = get_workspace_backend()
        backend.put_bytes("alice", "notes/a.txt", b"abc")
        snap = workspace_usage_snapshot("alice")
        assert snap["bytes_used"] == 3
        assert snap["backend"] == "minio"
