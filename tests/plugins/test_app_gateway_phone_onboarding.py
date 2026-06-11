"""Phone auth + onboarding initialization flow."""

from __future__ import annotations


def test_phone_register_and_onboarding(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text(
        "app_gateway:\n  jwt_secret: test-secret\n  auth_mode: dev\n  dev_sms_code: '111111'\n",
        encoding="utf-8",
    )

    from plugins.app_gateway.config import load_app_gateway_config
    from plugins.app_gateway.phone_auth import normalize_phone, verify_phone_login
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.onboarding import complete_onboarding, onboarding_status

    cfg = load_app_gateway_config()
    phone = normalize_phone("13800138111")
    from plugins.app_gateway.phone_auth import send_sms_code

    sent = send_sms_code(cfg, phone)
    assert sent["ok"] is True
    assert sent.get("sms_provider") == "dev"
    record, token, is_new = verify_phone_login(
        cfg, phone=phone, code="111111", device_id="iphone"
    )
    assert is_new
    assert token

    ctx = UserContext(
        user_id=record.user_id,
        session_id="app",
        device_id="iphone",
        raw_claims={"sub": record.user_id},
    )
    st0 = onboarding_status(ctx)
    assert st0["initialized"] is False
    assert st0["ready_for_chat"] is False

    done = complete_onboarding(
        ctx,
        api_key="user-test-key",
        model="anthropic/claude-sonnet-4",
        provider="openrouter",
    )
    assert done["initialized"] is True
    assert done["ready_for_chat"] is True

    st1 = onboarding_status(ctx)
    assert st1["ready_for_chat"] is True
