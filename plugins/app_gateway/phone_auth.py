"""Phone OTP registration/login and JWT issuance."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Optional, Tuple

from plugins.app_gateway.auth_tokens import issue_access_token
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.sms_provider import (
    SmsDeliveryError,
    deliver_sms,
    generate_otp,
    resolve_auth_mode,
)
from plugins.app_gateway.user_registry import AppUserRecord, get_user_registry

logger = logging.getLogger(__name__)

DEFAULT_SMS_CODE = "111111"


def normalize_phone(raw: str) -> str:
    """Normalize to digits; CN 11-digit mobile → 86 prefix."""
    s = re.sub(r"[\s\-()]", "", (raw or "").strip())
    if s.startswith("+"):
        s = s[1:]
    if not s.isdigit():
        raise ValueError("invalid phone number")
    if len(s) == 11 and s.startswith("1"):
        s = "86" + s
    if len(s) < 8 or len(s) > 16:
        raise ValueError("invalid phone number length")
    return s


def user_id_for_phone(phone: str) -> str:
    digest = hashlib.sha256(phone.encode("utf-8")).hexdigest()[:24]
    return f"u_{digest}"


def mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return "****"
    return phone[:3] + "****" + phone[-4:]


def fixed_sms_code(config: AppGatewayConfig) -> str:
    """Fixed OTP used only in ``auth_mode: dev``."""
    raw = str(getattr(config, "dev_sms_code", DEFAULT_SMS_CODE) or DEFAULT_SMS_CODE).strip()
    return raw or DEFAULT_SMS_CODE


def _should_expose_code(config: AppGatewayConfig) -> bool:
    return bool(getattr(config, "expose_dev_code", False))


def send_sms_code(config: AppGatewayConfig, phone: str) -> Dict[str, Any]:
    """Generate OTP, deliver via configured SMS provider, store for verification."""
    registry = get_user_registry()
    ttl = int(getattr(config, "sms_otp_ttl_seconds", 300) or 300)
    mode = resolve_auth_mode(config)

    if mode == "dev":
        code = fixed_sms_code(config)
        provider_name = "dev"
        try:
            deliver_sms(config, phone, code)
        except SmsDeliveryError as exc:
            logger.warning("dev SMS delivery skipped: %s", exc)
    else:
        code = generate_otp(6)
        provider_name = deliver_sms(config, phone, code)

    registry.store_otp(phone, code, ttl_seconds=ttl)

    expose = _should_expose_code(config)
    log_suffix = f" code={code}" if expose else ""
    logger.info(
        "SMS sent via %s to %s%s",
        provider_name,
        mask_phone(phone),
        log_suffix,
    )

    payload: Dict[str, Any] = {
        "ok": True,
        "phone": mask_phone(phone),
        "expires_in": ttl,
        "sms_provider": provider_name,
        "auth_mode": mode,
        "message": "verification code sent",
    }
    if expose:
        payload["code"] = code
        if mode == "dev":
            payload["dev_code"] = code
    return payload


def verify_phone_login(
    config: AppGatewayConfig,
    *,
    phone: str,
    code: str,
    device_id: Optional[str] = None,
    session_id: str = "app",
) -> Tuple[AppUserRecord, str, bool]:
    """Register or login; returns (record, access_token, is_new_user).

    Prefer ``AuthTokenService.issue_login_tokens`` when refresh tokens are needed.
    """
    registry = get_user_registry()
    submitted = str(code or "").strip()

    ok = registry.verify_otp(phone, submitted)

    if not ok:
        raise ValueError("invalid or expired verification code")

    existing = registry.get_by_phone(phone)
    is_new = existing is None
    uid = existing.user_id if existing else user_id_for_phone(phone)
    record = registry.upsert_user(uid, phone)
    token = issue_access_token(
        config,
        user_id=record.user_id,
        phone=phone,
        session_id=session_id,
        device_id=device_id,
    )
    return record, token, is_new
