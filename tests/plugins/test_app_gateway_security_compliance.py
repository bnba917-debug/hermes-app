"""Security, quotas, workspace paths, and compliance APIs for App Gateway."""

from __future__ import annotations

import pytest

from plugins.app_gateway.account_compliance import legal_document_path
from plugins.app_gateway.auth_limits import AuthAbuseLimiter
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.phone_auth import send_sms_code
from plugins.app_gateway.quotas import QuotaExceeded, UserQuotaManager
from plugins.app_gateway.user_scope import ensure_user_home, user_workspace
from plugins.app_gateway.workspace_paths import (
    resolve_app_gateway_path,
    validate_workspace_relative_path,
)


@pytest.fixture
def gw_config():
    return AppGatewayConfig(
        expose_dev_code=False,
        daily_chat_limit=2,
        max_concurrent_chats_per_user=1,
        auth_sms_per_ip_per_hour=2,
        auth_login_failures_per_phone=2,
    )


def test_validate_rejects_absolute_and_traversal():
    assert validate_workspace_relative_path("/etc/passwd")
    assert validate_workspace_relative_path("C:\\Windows\\System32")
    assert validate_workspace_relative_path("../secret.txt")


def test_resolve_stays_in_workspace(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home).mkdir()
    uid = "user-a"
    ensure_user_home(uid, include_global_skills=False)
    ws = user_workspace(uid)
    (ws / "notes").mkdir()
    (ws / "notes" / "a.txt").write_text("hi", encoding="utf-8")

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_scope import app_gateway_user_scope

    ctx = UserContext(user_id=uid, session_id="s1", device_id=None, raw_claims={})
    with app_gateway_user_scope(ctx):
        resolved, err = resolve_app_gateway_path("notes/a.txt")
        assert err is None
        assert resolved is not None
        assert resolved.name == "a.txt"

        _, err2 = resolve_app_gateway_path("../../outside.txt")
        assert err2 is not None


def test_send_sms_hides_code_by_default(gw_config, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from plugins.app_gateway.user_registry import reset_user_registry_cache

    reset_user_registry_cache()
    out = send_sms_code(gw_config, "+8613800138000")
    assert out["ok"] is True
    assert "code" not in out
    assert "dev_code" not in out


def test_send_sms_exposes_code_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from plugins.app_gateway.user_registry import reset_user_registry_cache

    reset_user_registry_cache()
    cfg = AppGatewayConfig(expose_dev_code=True)
    out = send_sms_code(cfg, "+8613800138001")
    assert out.get("code") == "111111"


def test_daily_chat_quota(gw_config):
    q = UserQuotaManager(gw_config)
    q.check_and_acquire_chat("u1")
    q.release_chat("u1")
    q.check_and_acquire_chat("u1")
    q.release_chat("u1")
    with pytest.raises(QuotaExceeded) as exc_info:
        q.check_and_acquire_chat("u1")
    assert exc_info.value.code == "daily_chat_limit"


def test_concurrent_quota(gw_config):
    q = UserQuotaManager(gw_config)
    q.check_and_acquire_chat("u2")
    with pytest.raises(QuotaExceeded) as exc_info:
        q.check_and_acquire_chat("u2")
    assert exc_info.value.code == "concurrent_limit"


def test_auth_sms_ip_limit(gw_config):
    lim = AuthAbuseLimiter(gw_config)
    lim.check_sms_send("1.2.3.4", "+8613800138002")
    lim.check_sms_send("1.2.3.4", "+8613800138003")
    with pytest.raises(ValueError, match="IP"):
        lim.check_sms_send("1.2.3.4", "+8613800138004")


def test_legal_docs_bundled():
    assert legal_document_path("terms") is not None
    assert legal_document_path("privacy") is not None
