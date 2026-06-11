"""Chat attachment uploads into user workspace."""

from __future__ import annotations

import pytest

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.chat_attachments import store_chat_attachment
from plugins.app_gateway.user_scope import user_workspace


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    return UserContext(
        user_id="u_test",
        session_id="app",
        device_id="web",
        raw_claims={"sub": "u_test"},
    )


def test_store_text_file_inline(ctx):
    data = store_chat_attachment(
        ctx,
        file_bytes=b"hello world\n",
        filename="note.txt",
        mime_type="text/plain",
    )
    assert data["ok"] is True
    assert data["kind"] == "text"
    assert data["inline_text"] == "hello world\n"
    path = user_workspace(ctx.user_id) / data["path"]
    assert path.is_file()


def test_store_binary_file(ctx):
    data = store_chat_attachment(
        ctx,
        file_bytes=b"%PDF-1.4",
        filename="doc.pdf",
        mime_type="application/pdf",
    )
    assert data["kind"] == "file"
    assert "inline_text" not in data


def test_reject_oversized(ctx):
    big = b"x" * (11 * 1024 * 1024)
    with pytest.raises(ValueError, match="too large"):
        store_chat_attachment(ctx, file_bytes=big, filename="big.bin")
