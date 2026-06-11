"""Per-user workspace + TERMINAL_CWD isolation for app gateway file tools."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path


def test_user_workspace_created(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.user_scope import ensure_user_home, user_workspace

    ensure_user_home("alice")
    ws = user_workspace("alice")
    assert ws.is_dir()
    assert (ws / "README.md").is_file()


def test_scope_sets_terminal_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_scope import app_gateway_user_scope, user_workspace
    from gateway.session_context import get_terminal_cwd

    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    expected = user_workspace("alice").resolve()

    prior = os.environ.get("TERMINAL_CWD")
    with app_gateway_user_scope(ctx):
        assert get_terminal_cwd() == str(expected)
        assert os.environ.get("TERMINAL_CWD") == str(expected)
    assert os.environ.get("TERMINAL_CWD") == prior


def test_file_tools_resolve_inside_user_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_scope import app_gateway_user_scope, user_workspace
    from tools.file_tools import _resolve_path_for_task

    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    ws = user_workspace("alice")

    with app_gateway_user_scope(ctx):
        target = _resolve_path_for_task("notes/hello.txt")
        assert target.relative_to(ws.resolve()) == Path("notes/hello.txt")


def test_concurrent_users_get_distinct_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_scope import app_gateway_user_scope, user_workspace
    from gateway.session_context import get_terminal_cwd

    results: dict[str, str] = {}

    def _run(user_id: str) -> None:
        ctx = UserContext(user_id=user_id, session_id="s1", device_id=None, raw_claims={})
        with app_gateway_user_scope(ctx):
            results[user_id] = get_terminal_cwd()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_a = pool.submit(copy_context().run, _run, "alice")
        f_b = pool.submit(copy_context().run, _run, "bob")
        f_a.result()
        f_b.result()

    assert results["alice"] == str(user_workspace("alice").resolve())
    assert results["bob"] == str(user_workspace("bob").resolve())
    assert results["alice"] != results["bob"]
