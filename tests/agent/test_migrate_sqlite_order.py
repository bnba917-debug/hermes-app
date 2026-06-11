"""Session parent/child ordering for SQLite → PG migration."""

from __future__ import annotations

from agent.session_storage.migrate_sqlite import _session_insert_order


def test_parent_before_child():
    rows = [
        {"id": "child", "parent_session_id": "parent"},
        {"id": "parent", "parent_session_id": None},
    ]
    ordered = _session_insert_order(rows)
    assert [r["id"] for r in ordered] == ["parent", "child"]
