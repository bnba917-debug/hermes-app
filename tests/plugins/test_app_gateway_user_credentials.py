"""Per-user API key isolation."""

from __future__ import annotations


def test_set_inference_marks_user_initialized(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    marked: list[str] = []

    class _FakeRegistry:
        def mark_initialized(self, user_id: str) -> None:
            marked.append(user_id)

    monkeypatch.setattr(
        "plugins.app_gateway.user_registry.get_user_registry",
        lambda: _FakeRegistry(),
    )

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_credentials import set_user_inference_config

    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    set_user_inference_config(
        ctx,
        api_key="alice-secret-key",
        provider="openrouter",
        model="alice-model",
    )

    assert marked == ["alice"]


def test_user_runtime_uses_own_env_not_global(tmp_path, monkeypatch):
    global_home = tmp_path / ".hermes"
    global_home.mkdir()
    (global_home / ".env").write_text("OPENROUTER_API_KEY=global-key\n", encoding="utf-8")
    (global_home / "config.yaml").write_text(
        "model:\n  provider: openrouter\n  default: gpt-test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(global_home))

    from plugins.app_gateway.user_scope import ensure_user_home, app_gateway_user_scope
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_credentials import (
        set_user_inference_config,
        resolve_user_runtime_kwargs,
    )

    ensure_user_home("alice")
    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    set_user_inference_config(
        ctx,
        api_key="alice-secret-key",
        provider="openrouter",
        model="alice-model",
    )

    with app_gateway_user_scope(ctx, include_global_skills=False):
        runtime = resolve_user_runtime_kwargs(fallback_global=False)
        assert runtime["api_key"] == "alice-secret-key"

    monkeypatch.setenv("OPENROUTER_API_KEY", "global-key")
    with app_gateway_user_scope(ctx, include_global_skills=False):
        runtime2 = resolve_user_runtime_kwargs(fallback_global=False)
        assert runtime2["api_key"] == "alice-secret-key"
