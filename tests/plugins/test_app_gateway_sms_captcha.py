"""Slider CAPTCHA before SMS send."""

from __future__ import annotations

import pytest

from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.server import create_app
from plugins.app_gateway.sms_captcha import (
    SmsCaptchaError,
    issue_sms_captcha,
    reset_sms_captcha_nonces_for_tests,
    verify_sms_captcha,
)


@pytest.fixture(autouse=True)
def _clear_captcha_nonces():
    reset_sms_captcha_nonces_for_tests()
    yield
    reset_sms_captcha_nonces_for_tests()


@pytest.fixture
def captcha_config():
    return AppGatewayConfig(
        jwt_secret="test-captcha-secret",
        sms_captcha_enabled=True,
    )


def test_issue_and_verify_slider_captcha(captcha_config):
    issued = issue_sms_captcha(captcha_config)
    assert issued["captcha_type"] == "slider"
    assert 150 <= issued["target_bp"] <= 850
    verify_sms_captcha(
        captcha_config,
        captcha_token=issued["captcha_token"],
        captcha_answer=str(issued["target_bp"]),
    )


def test_slider_within_tolerance(captcha_config):
    issued = issue_sms_captcha(captcha_config)
    target = issued["target_bp"]
    verify_sms_captcha(
        captcha_config,
        captcha_token=issued["captcha_token"],
        captcha_answer=str(target + 20),
    )


def test_wrong_slider_position_rejected(captcha_config):
    issued = issue_sms_captcha(captcha_config)
    with pytest.raises(SmsCaptchaError, match="incorrect"):
        verify_sms_captcha(
            captcha_config,
            captcha_token=issued["captcha_token"],
            captcha_answer=str(issued["target_bp"] + 200),
        )


def test_token_cannot_be_reused(captcha_config):
    issued = issue_sms_captcha(captcha_config)
    answer = str(issued["target_bp"])
    verify_sms_captcha(
        captcha_config,
        captcha_token=issued["captcha_token"],
        captcha_answer=answer,
    )
    with pytest.raises(SmsCaptchaError, match="already used"):
        verify_sms_captcha(
            captcha_config,
            captcha_token=issued["captcha_token"],
            captcha_answer=answer,
        )


def test_sms_send_requires_slider_captcha_over_http(captcha_config, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from plugins.app_gateway.user_registry import reset_user_registry_cache

    reset_user_registry_cache()
    captcha_config.auth_mode = "dev"
    captcha_config.expose_dev_code = True

    from fastapi.testclient import TestClient

    app = create_app(captcha_config)
    client = TestClient(app)

    denied = client.post("/v1/auth/sms/send", json={"phone": "13800138000"})
    assert denied.status_code == 400
    assert denied.json()["detail"]["code"] == "CAPTCHA_FAILED"

    cap = client.get("/v1/auth/sms/captcha")
    assert cap.status_code == 200
    data = cap.json()
    assert data["captcha_type"] == "slider"

    ok = client.post(
        "/v1/auth/sms/send",
        json={
            "phone": "13800138000",
            "captcha_token": data["captcha_token"],
            "captcha_answer": str(data["target_bp"]),
        },
    )
    assert ok.status_code == 200
    assert ok.json().get("ok") is True


def test_dev_login_rejects_code_without_sms_send(captcha_config, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from plugins.app_gateway.user_registry import reset_user_registry_cache

    reset_user_registry_cache()
    captcha_config.auth_mode = "dev"
    captcha_config.dev_sms_code = "111111"

    from fastapi.testclient import TestClient

    app = create_app(captcha_config)
    client = TestClient(app)

    denied = client.post(
        "/v1/auth/login",
        json={"phone": "13800138000", "code": "111111"},
    )
    assert denied.status_code in (400, 401)
    assert "invalid" in str(denied.json()["detail"]).lower()
