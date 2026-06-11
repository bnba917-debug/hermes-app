"""Gateway runtime cache and shared session store."""

from __future__ import annotations


def test_get_shared_session_db_singleton_sqlite(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_STORAGE_POSTGRES_URL", raising=False)
    (home / "config.yaml").write_text(
        "storage:\n  session_backend: sqlite\n",
        encoding="utf-8",
    )

    from hermes_state import get_shared_session_db, reset_shared_session_stores

    reset_shared_session_stores()
    a = get_shared_session_db()
    b = get_shared_session_db()
    assert a is b
    reset_shared_session_stores()


def test_gateway_agent_kit_warm_cache(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text(
        "model:\n  default: test-model\n",
        encoding="utf-8",
    )

    from gateway.runtime_cache import (
        get_gateway_agent_kit,
        invalidate_gateway_agent_kit,
    )

    invalidate_gateway_agent_kit()
    k1 = get_gateway_agent_kit(platform="api_server")
    k2 = get_gateway_agent_kit(platform="api_server")
    assert k1 is k2
    assert k1.model == "test-model"
    assert "api_server" in k1.toolsets_by_platform
