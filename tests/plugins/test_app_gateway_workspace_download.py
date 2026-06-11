"""Workspace file download API helpers."""

from __future__ import annotations

import json

import pytest


def test_extract_workspace_file_paths_write_file():
    from plugins.app_gateway.workspace_files import extract_workspace_file_paths

    paths = extract_workspace_file_paths(
        "write_file",
        {"path": "reports/summary.md", "content": "# hi"},
        json.dumps({"bytes_written": 4}),
    )
    assert paths == ["reports/summary.md"]

    blocked = extract_workspace_file_paths(
        "write_file",
        {"path": "reports/summary.md"},
        json.dumps({"error": "blocked"}),
    )
    assert blocked == []


def test_extract_workspace_file_paths_patch():
    from plugins.app_gateway.workspace_files import extract_workspace_file_paths

    result = json.dumps(
        {
            "success": True,
            "files_created": ["out/new.txt"],
            "files_modified": ["notes/todo.md"],
        }
    )
    paths = extract_workspace_file_paths("patch", {"path": "notes/todo.md"}, result)
    assert paths == ["out/new.txt", "notes/todo.md"]


def test_read_workspace_file_for_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.user_scope import user_workspace
    from plugins.app_gateway.workspace_files import read_workspace_file_for_user

    ws = user_workspace("alice")
    target = ws / "docs" / "hello.txt"
    target.parent.mkdir(parents=True)
    target.write_text("hello workspace", encoding="utf-8")

    payload = read_workspace_file_for_user("alice", "docs/hello.txt")
    assert payload.relative_path == "docs/hello.txt"
    assert payload.data == b"hello workspace"
    assert payload.filename == "hello.txt"


def test_read_workspace_file_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.workspace_files import read_workspace_file_for_user

    with pytest.raises(ValueError):
        read_workspace_file_for_user("alice", "../secret.txt")
