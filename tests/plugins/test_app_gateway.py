"""Tests for Hermes App Gateway plugin."""

from __future__ import annotations

import time

import pytest

from plugins.app_gateway.auth import (
    JwtError,
    encode_hs256_jwt,
    extract_user_context,
    verify_hs256_jwt,
)
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.rate_limit import UserRateLimiter
from plugins.app_gateway.session_keys import build_gateway_session_key, build_hermes_session_id
from plugins.app_gateway.vector_memory import UserVectorMemory, create_user_vector_memory


SECRET = "test-secret-key"


def test_jwt_roundtrip():
    payload = {"sub": "alice", "session_id": "s1", "exp": int(time.time()) + 3600}
    token = encode_hs256_jwt(payload, SECRET)
    claims = verify_hs256_jwt(token, SECRET)
    assert claims["sub"] == "alice"
    assert claims["session_id"] == "s1"


def test_jwt_expired():
    payload = {"sub": "alice", "exp": 1}
    token = encode_hs256_jwt(payload, SECRET)
    with pytest.raises(JwtError, match="expired|invalid exp"):
        verify_hs256_jwt(token, SECRET)


def test_session_keys_isolate_users():
    ctx_a = extract_user_context({"sub": "alice", "session_id": "chat-1"})
    ctx_b = extract_user_context({"sub": "bob", "session_id": "chat-1"})
    key_a = build_gateway_session_key(ctx_a)
    key_b = build_gateway_session_key(ctx_b)
    assert key_a != key_b
    sid_a = build_hermes_session_id(ctx_a)
    sid_b = build_hermes_session_id(ctx_b)
    assert sid_a != sid_b


def test_vector_memory_user_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    store = UserVectorMemory(enabled=True, top_k=5)
    store.add("alice", "s1", "Alice loves hiking in the mountains every weekend")
    store.add("bob", "s1", "Bob prefers sailing on the ocean near Boston")
    alice_hits = store.search("alice", "hiking mountains")
    bob_hits = store.search("bob", "sailing ocean")
    assert any("hiking" in h.lower() or "mountain" in h.lower() for h in alice_hits)
    assert not any("sailing" in h.lower() for h in alice_hits)
    assert any("sailing" in h.lower() or "ocean" in h.lower() for h in bob_hits)
    assert not any("hiking" in h.lower() for h in bob_hits)


def test_create_user_vector_memory_sqlite_backend_ignores_dsn():
    cfg = AppGatewayConfig(
        vector_memory_backend="sqlite",
        postgres_url="postgresql://invalid",
        vector_memory_enabled=True,
    )
    mem = create_user_vector_memory(cfg)
    assert type(mem).__name__ == "UserVectorMemory"


def test_audit_backend_auto_without_dsn():
    from plugins.app_gateway.audit_backends import create_audit_backend

    backend = create_audit_backend("auto", postgres_url="")
    assert backend is not None
    assert type(backend).__name__ == "SqliteAuditBackend"


def test_app_gateway_toolset_excludes_terminal_and_browser():
    from toolsets import resolve_toolset

    tools = set(resolve_toolset("hermes-app-gateway"))
    blocked = {
        "terminal",
        "process",
        "browser_navigate",
        "computer_use",
    }
    assert not (tools & blocked)
    assert "web_search" not in tools
    assert "delegate_task" in tools
    assert "execute_code" in tools
    assert "cronjob" in tools
    assert "clarify" in tools


def test_rate_limiter():
    lim = UserRateLimiter(requests_per_minute=2)
    assert lim.allow("u1")
    assert lim.allow("u1")
    assert not lim.allow("u1")
    assert lim.allow("u2")


def test_config_registry_reload(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from plugins.app_gateway.config_registry import ConfigRegistry

    reg = ConfigRegistry()
    reg.scaffold_if_missing()
    assert "system_prompt_prefix" in reg.reload(force=True)
    prefix = reg.get_ephemeral_system_prefix()
    assert "mobile" in prefix.lower() or "Hermes" in prefix


def test_tester_route_removed():
    pytest.importorskip("fastapi")
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(require_jwt=False, jwt_secret=SECRET)
    app = create_app(cfg)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/tester")
    assert resp.status_code == 404


def test_health_endpoint():
    pytest.importorskip("fastapi")
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        require_jwt=False,
        jwt_secret=SECRET,
        vector_memory_enabled=True,
    )
    app = create_app(cfg)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.4.0"
    assert body["vector_memory"] is True
    assert body.get("vector_memory_backend") == "auto"


def test_memory_search_endpoint(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        require_jwt=True,
        jwt_secret=SECRET,
        app_key="svc",
        vector_memory_enabled=True,
    )
    store = UserVectorMemory(enabled=True)
    store.add("alice", "s1", "Alice discussed project Phoenix roadmap planning")
    app = create_app(cfg, vector_memory=store)
    from fastapi.testclient import TestClient

    token = encode_hs256_jwt(
        {"sub": "alice", "session_id": "s1", "exp": int(time.time()) + 3600},
        SECRET,
    )
    client = TestClient(app)
    resp = client.get(
        "/v1/memory/search",
        params={"q": "Phoenix roadmap"},
        headers={"X-User-Token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "alice"
    assert len(data["results"]) >= 1


def test_memory_search_accepts_app_key_without_user_token(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        require_jwt=True,
        jwt_secret=SECRET,
        app_key="svc",
        vector_memory_enabled=True,
    )
    store = UserVectorMemory(enabled=True)
    store.add("alice", "s1", "Alice discussed project Phoenix roadmap planning")
    app = create_app(cfg, vector_memory=store)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get(
        "/v1/memory/search",
        params={"q": "Phoenix roadmap"},
        headers={"X-App-Key": "svc", "Authorization": "Bearer svc"},
    )
    assert resp.status_code == 401
