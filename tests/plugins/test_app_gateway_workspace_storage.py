"""Workspace storage usage controls."""

from __future__ import annotations

import time

import pytest

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.config import AppGatewayConfig


@pytest.fixture
def workspace_ctx(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return UserContext(
        user_id="storage-user",
        session_id="app",
        device_id="web",
        raw_claims={"sub": "storage-user"},
    )


def test_workspace_usage_snapshot_counts_files(workspace_ctx):
    from plugins.app_gateway.user_scope import ensure_user_home, user_workspace
    from plugins.app_gateway.workspace_storage import workspace_usage_snapshot

    ensure_user_home(workspace_ctx.user_id, include_global_skills=False)
    ws = user_workspace(workspace_ctx.user_id)
    (ws / "notes").mkdir()
    (ws / "notes" / "a.txt").write_bytes(b"abc")
    (ws / "uploads").mkdir(exist_ok=True)
    (ws / "uploads" / "b.bin").write_bytes(b"12345")

    snapshot = workspace_usage_snapshot(workspace_ctx.user_id)

    assert snapshot["bytes_used"] == 8
    assert snapshot["file_count"] == 2
    assert snapshot["uploads_bytes"] == 5


def test_local_workspace_usage_snapshot_ignores_remote(monkeypatch, workspace_ctx):
    from plugins.app_gateway.user_scope import ensure_user_home, user_workspace
    from plugins.app_gateway.workspace_storage import local_workspace_usage_snapshot

    ensure_user_home(workspace_ctx.user_id, include_global_skills=False)
    ws = user_workspace(workspace_ctx.user_id)
    (ws / "local.txt").write_bytes(b"abcd")

    def _boom(*_a, **_k):
        raise AssertionError("list_objects must not run for local snapshot")

    monkeypatch.setattr(
        "plugins.app_gateway.workspace_storage.get_workspace_backend",
        lambda: type("B", (), {"backend_name": lambda self: "minio", "list_objects": _boom})(),
    )

    snap = local_workspace_usage_snapshot(workspace_ctx.user_id)
    assert snap["bytes_used"] == 4
    assert snap["source"] == "local"


def test_me_storage_endpoint_returns_usage(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.server import create_app
    from plugins.app_gateway.user_scope import ensure_user_home, user_workspace

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    secret = "secret"
    cfg = AppGatewayConfig(
        require_jwt=True,
        jwt_secret=secret,
    )
    app = create_app(cfg)
    ensure_user_home("storage-user", include_global_skills=False)
    (user_workspace("storage-user") / "note.txt").write_bytes(b"hello")
    token = encode_hs256_jwt(
        {"sub": "storage-user", "session_id": "app", "exp": int(time.time()) + 3600},
        secret,
    )

    resp = TestClient(app).get(
        "/v1/me/storage",
        headers={"X-User-Token": token},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "storage-user"
    assert body["bytes_used"] == 5
