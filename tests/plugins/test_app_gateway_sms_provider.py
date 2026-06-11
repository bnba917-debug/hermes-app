"""SMS provider delivery (mocked HTTP — no real sends)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.phone_auth import send_sms_code, verify_phone_login
from plugins.app_gateway.sms_provider import (
    AliyunSmsProvider,
    SmsDeliveryError,
    deliver_sms,
    generate_otp,
    resolve_auth_mode,
)
from plugins.app_gateway.user_registry import reset_user_registry_cache


def test_generate_otp_length():
    code = generate_otp(6)
    assert len(code) == 6
    assert code.isdigit()


def test_aliyun_send_success(monkeypatch):
    monkeypatch.setenv("ALIYUN_SMS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("ALIYUN_SMS_ACCESS_KEY_SECRET", "secret")
    cfg = AppGatewayConfig(
        auth_mode="aliyun",
        sms_sign_name="Hermes",
        sms_template_code="SMS_123",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Code": "OK", "Message": "OK"}

    with patch("plugins.app_gateway.sms_provider.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = mock_resp
        AliyunSmsProvider().send("8613800138000", "654321", cfg)

    assert client.get.called


def test_aliyun_send_vendor_error(monkeypatch):
    monkeypatch.setenv("ALIYUN_SMS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("ALIYUN_SMS_ACCESS_KEY_SECRET", "secret")
    cfg = AppGatewayConfig(
        auth_mode="aliyun",
        sms_sign_name="Hermes",
        sms_template_code="SMS_123",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Code": "isv.BUSINESS_LIMIT_CONTROL", "Message": "limit"}

    with patch("plugins.app_gateway.sms_provider.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = mock_resp
        with pytest.raises(SmsDeliveryError):
            AliyunSmsProvider().send("8613800138000", "654321", cfg)


def test_production_send_stores_random_otp(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    reset_user_registry_cache()
    monkeypatch.setenv("ALIYUN_SMS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("ALIYUN_SMS_ACCESS_KEY_SECRET", "secret")

    cfg = AppGatewayConfig(
        auth_mode="aliyun",
        jwt_secret="jwt-test",
        sms_sign_name="Hermes",
        sms_template_code="SMS_123",
        expose_dev_code=False,
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Code": "OK"}

    phone = "8613800138002"
    captured_code = {}

    def fake_send(self, p, code, c):
        captured_code["code"] = code

    with patch.object(AliyunSmsProvider, "send", fake_send):
        out = send_sms_code(cfg, phone)

    assert out["ok"] is True
    assert "code" not in out
    assert captured_code["code"]
    record, token, _ = verify_phone_login(
        cfg, phone=phone, code=captured_code["code"], device_id="t"
    )
    assert token
    assert record.phone == phone


def test_resolve_auth_mode_env_override(monkeypatch):
    cfg = AppGatewayConfig(auth_mode="dev")
    monkeypatch.setenv("APP_GATEWAY_AUTH_MODE", "aliyun")
    assert resolve_auth_mode(cfg) == "aliyun"
