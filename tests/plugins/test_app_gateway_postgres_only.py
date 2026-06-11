"""PG-only mode — refuse SQLite fallbacks for App Gateway storage."""

from __future__ import annotations

import pytest
import yaml

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.postgres_policy import PostgresOnlyError


def _write_config(home, *, postgres_only: bool, postgres_url: str = "", **overrides):
    home.mkdir(parents=True, exist_ok=True)
    payload = {
        "storage": {
            "postgres_only": postgres_only,
            "postgres_url": postgres_url,
        },
        "app_gateway": {
            "jwt_secret": "test-secret",
            "postgres_only": postgres_only,
            "postgres_url": postgres_url,
            **overrides,
        },
    }
    (home / "config.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True),
        encoding="utf-8",
    )


def test_load_postgres_only_from_storage_section(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    _write_config(home, postgres_only=True, postgres_url="postgresql://x")
    monkeypatch.setenv("HERMES_HOME", str(home))

    from plugins.app_gateway.postgres_policy import load_postgres_only_flag

    assert load_postgres_only_flag() is True


def test_session_backend_sqlite_forbidden_when_pg_only(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {
                    "postgres_only": True,
                    "postgres_url": "postgresql://x",
                    "session_backend": "sqlite",
                },
                "app_gateway": {"jwt_secret": "test-secret"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))

    from agent.session_storage.config import resolve_session_backend

    with pytest.raises(PostgresOnlyError, match="session_backend=sqlite"):
        resolve_session_backend()


def test_user_registry_sqlite_forbidden_when_pg_only(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {"postgres_only": True, "postgres_url": "postgresql://x"},
                "app_gateway": {
                    "jwt_secret": "test-secret",
                    "user_registry_backend": "sqlite",
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))

    from plugins.app_gateway.user_registry_factory import resolve_user_registry_backend

    with pytest.raises(PostgresOnlyError, match="user_registry"):
        resolve_user_registry_backend()


def test_audit_sqlite_forbidden_when_pg_only():
    from plugins.app_gateway.audit_backends import create_audit_backend

    with pytest.raises(PostgresOnlyError, match="audit"):
        create_audit_backend("sqlite", postgres_only=True)


def test_audit_dual_forbidden_when_pg_only():
    from plugins.app_gateway.audit_backends import create_audit_backend

    with pytest.raises(PostgresOnlyError, match="dual"):
        create_audit_backend("dual", postgres_url="postgresql://x", postgres_only=True)


def test_vector_memory_sqlite_forbidden_when_pg_only():
    cfg = AppGatewayConfig(
        vector_memory_backend="sqlite",
        postgres_only=True,
        postgres_url="postgresql://x",
    )

    from plugins.app_gateway.vector_memory import create_user_vector_memory

    with pytest.raises(PostgresOnlyError, match="vector_memory"):
        create_user_vector_memory(cfg)


def test_get_shared_session_db_rejects_sqlite_fallback(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    _write_config(home, postgres_only=True, postgres_url="")
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_state import get_shared_session_db

    with pytest.raises(PostgresOnlyError, match="postgres_url"):
        get_shared_session_db()


def test_get_shared_session_db_rejects_explicit_db_path(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    _write_config(home, postgres_only=True, postgres_url="postgresql://x")
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_state import get_shared_session_db

    with pytest.raises(PostgresOnlyError, match="db_path"):
        get_shared_session_db(db_path=home / "state.db")


def test_create_app_fails_without_postgres_url_when_pg_only(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    home = tmp_path / ".hermes"
    _write_config(home, postgres_only=True, postgres_url="")
    monkeypatch.setenv("HERMES_HOME", str(home))

    from plugins.app_gateway.config import load_app_gateway_config
    from plugins.app_gateway.server import create_app

    cfg = load_app_gateway_config()
    assert cfg.postgres_only is True

    with pytest.raises(PostgresOnlyError, match="postgres_url"):
        create_app(cfg)


def test_health_shows_postgres_only_flag():
    pytest.importorskip("fastapi")
    from unittest.mock import MagicMock, patch

    from plugins.app_gateway.server import create_app

    cfg = AppGatewayConfig(
        require_jwt=False,
        jwt_secret="s",
        postgres_only=True,
        postgres_url="postgresql://localhost/hermes",
        audit_backend="postgres",
    )
    vector = MagicMock(enabled=True)
    with patch("plugins.app_gateway.postgres_policy.validate_app_gateway_postgres_only"), patch(
        "plugins.app_gateway.redis_policy.validate_app_gateway_redis"
    ), patch(
        "plugins.app_gateway.audit_backends.PostgresAuditBackend",
        return_value=MagicMock(),
    ):
        app = create_app(cfg, vector_memory=vector)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["postgres_only"] is True
