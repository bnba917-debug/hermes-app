"""Kanban/cron storage backend resolution."""

from __future__ import annotations

import pytest

from agent.session_storage.config import resolve_cron_backend, resolve_kanban_backend


def test_kanban_explicit_path_forces_sqlite():
    backend, dsn = resolve_kanban_backend("/tmp/kanban.db")
    assert backend == "sqlite"
    assert dsn is None


def test_cron_auto_postgres(monkeypatch):
    monkeypatch.setattr(
        "agent.session_storage.config._load_storage_config",
        lambda: (
            {
                "cron_backend": "auto",
                "postgres_url": "postgresql://localhost/hermes",
            },
            {},
        ),
    )
    backend, dsn = resolve_cron_backend()
    assert backend == "postgres"
    assert "postgresql://" in (dsn or "")
