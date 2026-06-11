"""Outbound SMS providers for App Gateway phone OTP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import httpx

from plugins.app_gateway.config import AppGatewayConfig

logger = logging.getLogger(__name__)


class SmsDeliveryError(RuntimeError):
    """Raised when the vendor rejects or fails to send SMS."""


class SmsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, phone: str, code: str, config: AppGatewayConfig) -> None:
        """Deliver ``code`` to ``phone`` (E.164-ish digits, often 86-prefixed)."""


def generate_otp(length: int = 6) -> str:
    n = max(4, min(int(length or 6), 8))
    upper = 10**n
    return f"{secrets.randbelow(upper):0{n}d}"


def _cfg_sms(config: AppGatewayConfig, key: str, default: str = "") -> str:
    block = getattr(config, "sms", None)
    if isinstance(block, dict):
        val = block.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return str(getattr(config, key, default) or default).strip()


def _env(*names: str) -> str:
    for name in names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _phone_for_aliyun(phone: str) -> str:
    """Aliyun domestic: 11-digit mobile; intl: keep 86 prefix without +."""
    if phone.startswith("86") and len(phone) == 13:
        return phone[2:]
    return phone


def _phone_e164(phone: str) -> str:
    return f"+{phone}" if not phone.startswith("+") else phone


class DevSmsProvider(SmsProvider):
    name = "dev"

    def send(self, phone: str, code: str, config: AppGatewayConfig) -> None:
        logger.info("dev SMS (no send) phone=%s", phone[:3] + "****")


class AliyunSmsProvider(SmsProvider):
    name = "aliyun"

    def send(self, phone: str, code: str, config: AppGatewayConfig) -> None:
        access_key = _env("ALIYUN_SMS_ACCESS_KEY_ID", "APP_GATEWAY_SMS_ACCESS_KEY_ID")
        secret = _env("ALIYUN_SMS_ACCESS_KEY_SECRET", "APP_GATEWAY_SMS_SECRET_KEY")
        sign_name = _env("ALIYUN_SMS_SIGN_NAME") or _cfg_sms(config, "sms_sign_name")
        template = _env("ALIYUN_SMS_TEMPLATE_CODE") or _cfg_sms(config, "sms_template_code")
        param_name = _cfg_sms(config, "sms_template_param", "code") or "code"
        region = _cfg_sms(config, "sms_region", "cn-hangzhou") or "cn-hangzhou"

        if not access_key or not secret:
            raise SmsDeliveryError(
                "Aliyun SMS requires ALIYUN_SMS_ACCESS_KEY_ID and ALIYUN_SMS_ACCESS_KEY_SECRET"
            )
        if not sign_name or not template:
            raise SmsDeliveryError(
                "Aliyun SMS requires sms_sign_name and sms_template_code in config or env"
            )

        params: Dict[str, str] = {
            "AccessKeyId": access_key,
            "Action": "SendSms",
            "Format": "JSON",
            "PhoneNumbers": _phone_for_aliyun(phone),
            "RegionId": region,
            "SignName": sign_name,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": uuid.uuid4().hex,
            "SignatureVersion": "1.0",
            "TemplateCode": template,
            "TemplateParam": json.dumps({param_name: code}, ensure_ascii=False),
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version": "2017-05-25",
        }
        params["Signature"] = _aliyun_signature(params, secret)
        url = "https://dysmsapi.aliyuncs.com/"
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
        try:
            data = resp.json()
        except Exception as exc:
            raise SmsDeliveryError(f"Aliyun SMS invalid response: {resp.text[:200]}") from exc
        if resp.status_code >= 400:
            raise SmsDeliveryError(f"Aliyun SMS HTTP {resp.status_code}: {data}")
        if str(data.get("Code") or "") != "OK":
            raise SmsDeliveryError(f"Aliyun SMS error: {data.get('Message') or data}")


def _aliyun_signature(params: Dict[str, str], secret: str) -> str:
    sorted_items = sorted(params.items())
    canonical = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_items
    )
    string_to_sign = f"GET&{_percent_encode('/')}&{_percent_encode(canonical)}"
    digest = hmac.new(
        f"{secret}&".encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _percent_encode(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


class TencentSmsProvider(SmsProvider):
    name = "tencent"

    def send(self, phone: str, code: str, config: AppGatewayConfig) -> None:
        secret_id = _env("TENCENT_SMS_SECRET_ID", "APP_GATEWAY_SMS_SECRET_ID")
        secret_key = _env("TENCENT_SMS_SECRET_KEY", "APP_GATEWAY_SMS_SECRET_KEY")
        sdk_app_id = _env("TENCENT_SMS_SDK_APP_ID") or _cfg_sms(config, "sms_sdk_app_id")
        template_id = _env("TENCENT_SMS_TEMPLATE_ID") or _cfg_sms(config, "sms_template_id")
        sign_name = _env("TENCENT_SMS_SIGN_NAME") or _cfg_sms(config, "sms_sign_name")
        region = _cfg_sms(config, "sms_region", "ap-guangzhou") or "ap-guangzhou"

        if not secret_id or not secret_key:
            raise SmsDeliveryError(
                "Tencent SMS requires TENCENT_SMS_SECRET_ID and TENCENT_SMS_SECRET_KEY"
            )
        if not sdk_app_id or not template_id:
            raise SmsDeliveryError(
                "Tencent SMS requires sms_sdk_app_id and sms_template_id"
            )

        payload = {
            "PhoneNumberSet": [_phone_e164(phone)],
            "SmsSdkAppId": sdk_app_id,
            "TemplateId": template_id,
            "TemplateParamSet": [code],
        }
        if sign_name:
            payload["SignName"] = sign_name

        host = "sms.tencentcloudapi.com"
        service = "sms"
        body = json.dumps(payload, separators=(",", ":"))
        headers = _tencent_tc3_headers(
            secret_id=secret_id,
            secret_key=secret_key,
            host=host,
            service=service,
            region=region,
            action="SendSms",
            version="2021-01-11",
            payload=body,
        )
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"https://{host}", content=body, headers=headers)
        try:
            data = resp.json()
        except Exception as exc:
            raise SmsDeliveryError(f"Tencent SMS invalid response: {resp.text[:200]}") from exc
        if resp.status_code >= 400:
            raise SmsDeliveryError(f"Tencent SMS HTTP {resp.status_code}: {data}")
        resp_block = (data.get("Response") or {}) if isinstance(data, dict) else {}
        err = resp_block.get("Error")
        if err:
            raise SmsDeliveryError(f"Tencent SMS error: {err}")
        send_status = ((resp_block.get("SendStatusSet") or [{}])[0]) or {}
        if send_status.get("Code") not in (None, "Ok", "OK"):
            raise SmsDeliveryError(f"Tencent SMS send failed: {send_status}")


def _tencent_tc3_headers(
    *,
    secret_id: str,
    secret_key: str,
    host: str,
    service: str,
    region: str,
    action: str,
    version: str,
    payload: str,
) -> Dict[str, str]:
    timestamp = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, hashed_payload]
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _hmac_sha256(f"TC3{secret_key}".encode("utf-8"), date.encode("utf-8"))
    secret_service = _hmac_sha256(secret_date, service.encode("utf-8"))
    secret_signing = _hmac_sha256(secret_service, b"tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


class TwilioSmsProvider(SmsProvider):
    name = "twilio"

    def send(self, phone: str, code: str, config: AppGatewayConfig) -> None:
        account_sid = _env("TWILIO_ACCOUNT_SID", "APP_GATEWAY_TWILIO_ACCOUNT_SID")
        auth_token = _env("TWILIO_AUTH_TOKEN", "APP_GATEWAY_TWILIO_AUTH_TOKEN")
        from_number = _env("TWILIO_SMS_FROM") or _cfg_sms(config, "sms_from_number")
        if not account_sid or not auth_token or not from_number:
            raise SmsDeliveryError(
                "Twilio SMS requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_FROM"
            )
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        body = {
            "To": _phone_e164(phone),
            "From": from_number,
            "Body": _cfg_sms(config, "sms_message_template", "Your verification code is {code}").format(
                code=code
            ),
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, data=body, auth=(account_sid, auth_token))
        if resp.status_code >= 400:
            raise SmsDeliveryError(f"Twilio SMS HTTP {resp.status_code}: {resp.text[:200]}")


class HttpWebhookSmsProvider(SmsProvider):
    """POST JSON to a custom URL (self-hosted SMS bridge)."""

    name = "http"

    def send(self, phone: str, code: str, config: AppGatewayConfig) -> None:
        url = _env("APP_GATEWAY_SMS_WEBHOOK_URL") or _cfg_sms(config, "sms_webhook_url")
        if not url:
            raise SmsDeliveryError("HTTP SMS requires sms_webhook_url in config or APP_GATEWAY_SMS_WEBHOOK_URL")
        payload = {"phone": phone, "code": code}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload)
        if resp.status_code >= 400:
            raise SmsDeliveryError(f"SMS webhook HTTP {resp.status_code}: {resp.text[:200]}")


_PROVIDERS: Dict[str, SmsProvider] = {
    "dev": DevSmsProvider(),
    "aliyun": AliyunSmsProvider(),
    "tencent": TencentSmsProvider(),
    "twilio": TwilioSmsProvider(),
    "http": HttpWebhookSmsProvider(),
    "webhook": HttpWebhookSmsProvider(),
}


def resolve_auth_mode(config: AppGatewayConfig) -> str:
    raw = (
        os.environ.get("APP_GATEWAY_AUTH_MODE", "").strip().lower()
        or str(getattr(config, "auth_mode", "dev") or "dev").strip().lower()
    )
    return raw or "dev"


def get_sms_provider(config: AppGatewayConfig) -> SmsProvider:
    mode = resolve_auth_mode(config)
    provider = _PROVIDERS.get(mode)
    if provider is None:
        raise SmsDeliveryError(f"Unknown app_gateway.auth_mode / SMS provider: {mode}")
    return provider


def deliver_sms(config: AppGatewayConfig, phone: str, code: str) -> str:
    """Send OTP via configured provider; returns provider name."""
    mode = resolve_auth_mode(config)
    if mode == "dev":
        DevSmsProvider().send(phone, code, config)
        return "dev"
    provider = get_sms_provider(config)
    provider.send(phone, code, config)
    return provider.name
