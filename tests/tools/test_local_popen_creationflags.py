"""Windows LocalEnvironment must not pass creationflags twice to Popen."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from tools.environments.local import LocalEnvironment


def test_windows_spawn_passes_creationflags_once(monkeypatch):
    monkeypatch.setattr("tools.environments.local._IS_WINDOWS", True)

    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.stdout = MagicMock(
            __iter__=lambda s: iter([]),
            __next__=lambda s: (_ for _ in ()).throw(StopIteration()),
        )
        proc.stdin = MagicMock()
        return proc

    fake_interrupt = threading.Event()
    env = LocalEnvironment(cwd="/tmp", timeout=10)

    with patch("tools.environments.local._find_bash", return_value="/bin/bash"), \
         patch("subprocess.Popen", side_effect=fake_popen) as popen_mock, \
         patch("tools.terminal_tool._interrupt_event", fake_interrupt):
        env.execute("echo hello")

    popen_mock.assert_called_once()
    assert "creationflags" in captured
    assert captured["creationflags"] != 0
