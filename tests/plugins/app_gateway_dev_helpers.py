"""Shared helpers for App Gateway plugin tests."""

from __future__ import annotations


def seed_dev_sms_otp(
    phone: str,
    code: str = "111111",
    *,
    ttl_seconds: int = 300,
) -> str:
    """Store a dev OTP as if ``send_sms_code`` had been called."""
    from plugins.app_gateway.phone_auth import normalize_phone
    from plugins.app_gateway.user_registry import get_user_registry

    normalized = normalize_phone(phone)
    get_user_registry().store_otp(normalized, code, ttl_seconds=ttl_seconds)
    return normalized
