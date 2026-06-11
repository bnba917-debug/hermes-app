"""Regression: SSE chat stream must not crash in event_generator finally."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def gateway_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_stream_chat_event_generator_releases_quota_without_unbound_error(gateway_home, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from plugins.app_gateway.auth import encode_hs256_jwt
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.server import create_app

    async def fake_run_chat(self, *args, **kwargs):
        cb = kwargs.get("stream_delta_callback")
        if cb:
            cb("ok")
        return (
            {"final_response": "ok", "session_id": "sid", "error": None},
            {"total_tokens": 1},
        )

    monkeypatch.setattr(
        "plugins.app_gateway.runtime.AppAgentRuntime.run_chat",
        fake_run_chat,
    )
    monkeypatch.setattr(
        "plugins.app_gateway.runtime.AppAgentRuntime.load_history",
        lambda self, ctx, session_id: [],
    )

    secret = "stream-quota-secret"
    cfg = AppGatewayConfig(
        jwt_secret=secret,
        auth_mode="dev",
        dev_sms_code="111111",
        require_jwt=True,
        require_onboarding_before_chat=False,
    )
    app = create_app(cfg)

    token = encode_hs256_jwt(
        {"sub": "u-stream", "session_id": "app", "exp": 9999999999},
        secret,
    )
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Hermes-Session-Id": "stream-s1",
        },
        json={
            "messages": [{"role": "user", "content": "帮我创建一个学习英文单词的skill"}],
            "stream": True,
        },
    )
    assert resp.status_code == 200
    assert "data:" in resp.text
    assert "[DONE]" in resp.text
