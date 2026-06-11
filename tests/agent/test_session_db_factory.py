"""SessionDB factory selects SQLite vs PostgreSQL."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_session_db_explicit_path_is_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", "postgresql://localhost/hermes")
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    assert type(db).__name__ == "SessionDB"
    assert hasattr(db, "_conn")


def test_session_db_factory_postgres_when_configured(monkeypatch):
    monkeypatch.setattr(
        "agent.session_storage.config._load_storage_config",
        lambda: (
            {"session_backend": "postgres", "postgres_url": "postgresql://test/db"},
            {},
        ),
    )
    from unittest.mock import MagicMock, patch

    fake_pg = MagicMock()
    fake_pg.backend = "postgres"
    with patch(
        "agent.session_storage.postgres_session_db.get_postgres_session_db",
        return_value=fake_pg,
    ):
        from hermes_state import SessionDB

        db = SessionDB()
    assert db is fake_pg
