"""Session storage backend resolution (no live PostgreSQL required)."""

from __future__ import annotations

import pytest

from agent.session_storage.config import (
    resolve_postgres_url,
    resolve_session_backend,
)


def test_explicit_db_path_forces_sqlite(monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", "postgresql://u:p@localhost/db")
    backend, dsn = resolve_session_backend("/tmp/custom.db")
    assert backend == "sqlite"
    assert dsn is None


def test_auto_uses_postgres_when_dsn_set(monkeypatch):
    monkeypatch.delenv("HERMES_STORAGE_POSTGRES_URL", raising=False)
    monkeypatch.setattr(
        "agent.session_storage.config._load_storage_config",
        lambda: ({"session_backend": "auto", "postgres_url": "postgresql://a/b"}, {}),
    )
    backend, dsn = resolve_session_backend()
    assert backend == "postgres"
    assert dsn == "postgresql://a/b"


def test_postgres_without_url_falls_back_sqlite(monkeypatch):
    monkeypatch.setattr(
        "agent.session_storage.config._load_storage_config",
        lambda: ({"session_backend": "postgres", "postgres_url": ""}, {}),
    )
    backend, dsn = resolve_session_backend()
    assert backend == "sqlite"
    assert dsn is None


def test_resolve_postgres_url_env_priority(monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", "postgresql://env/db")
    monkeypatch.setattr(
        "agent.session_storage.config._load_storage_config",
        lambda: ({"postgres_url": "postgresql://storage/db"}, {"postgres_url": "postgresql://app/db"}),
    )
    assert resolve_postgres_url() == "postgresql://env/db"
