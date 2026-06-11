"""Slider CAPTCHA before SMS send (signed token + one-time nonce)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import random
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

from plugins.app_gateway.config import AppGatewayConfig

_USED_NONCES: Dict[str, float] = {}
_NONCE_LOCK = threading.Lock()
_CAPTCHA_KIND = "slider"


class SmsCaptchaError(ValueError):
    """Invalid, expired, or reused CAPTCHA."""


def sms_captcha_enabled(config: AppGatewayConfig) -> bool:
    return bool(getattr(config, "sms_captcha_enabled", True))


def _captcha_secret(config: AppGatewayConfig) -> str:
    secret = (getattr(config, "jwt_secret", None) or "").strip()
    if not secret:
        raise SmsCaptchaError("jwt_secret is required when sms_captcha_enabled is true")
    return secret


def _ttl_seconds(config: AppGatewayConfig) -> int:
    return max(60, min(int(getattr(config, "sms_captcha_ttl_seconds", 300) or 300), 900))


def _tolerance_bp(config: AppGatewayConfig) -> int:
    return max(10, min(int(getattr(config, "sms_captcha_tolerance_bp", 35) or 35), 120))


def _prune_used_nonces(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    expired = [n for n, exp in _USED_NONCES.items() if exp < now]
    for n in expired:
        _USED_NONCES.pop(n, None)


def _sign_payload(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_token(payload: str, signature: str) -> str:
    raw = f"{payload}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_token(token: str) -> Tuple[str, str]:
    pad = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode((token + pad).encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise SmsCaptchaError("invalid captcha token") from exc
    if "|" not in raw:
        raise SmsCaptchaError("invalid captcha token")
    payload, signature = raw.rsplit("|", 1)
    if not payload or not signature:
        raise SmsCaptchaError("invalid captcha token")
    return payload, signature


def _generate_slider_target_bp() -> int:
    """Target position in permille (150–850 → 15%–85% of track)."""
    return random.randint(150, 850)


def issue_sms_captcha(config: AppGatewayConfig) -> Dict[str, Any]:
    """Return a slider challenge and signed one-time token."""
    secret = _captcha_secret(config)
    ttl = _ttl_seconds(config)
    target_bp = _generate_slider_target_bp()
    exp = int(time.time()) + ttl
    nonce = secrets.token_hex(8)
    payload = f"{_CAPTCHA_KIND}|{target_bp}|{exp}|{nonce}"
    token = _encode_token(payload, _sign_payload(secret, payload))
    return {
        "enabled": True,
        "captcha_type": _CAPTCHA_KIND,
        "captcha_token": token,
        "target_ratio": round(target_bp / 1000.0, 3),
        "target_bp": target_bp,
        "tolerance_bp": _tolerance_bp(config),
        "expires_in": ttl,
    }


def _parse_slider_answer(raw_answer: str) -> int:
    cleaned = (raw_answer or "").strip()
    if not cleaned or not cleaned.isdigit():
        raise SmsCaptchaError("captcha_answer must be a slider position (0-1000)")
    value = int(cleaned)
    if value < 0 or value > 1000:
        raise SmsCaptchaError("captcha_answer must be between 0 and 1000")
    return value


def verify_sms_captcha(
    config: AppGatewayConfig,
    *,
    captcha_token: str,
    captcha_answer: str,
    consume: bool = True,
) -> None:
    """Validate slider position; raises SmsCaptchaError on failure."""
    if not sms_captcha_enabled(config):
        return
    token = (captcha_token or "").strip()
    if not token:
        raise SmsCaptchaError("captcha_token is required")
    submitted_bp = _parse_slider_answer(captcha_answer)

    secret = _captcha_secret(config)
    try:
        payload, signature = _decode_token(token)
    except SmsCaptchaError:
        raise
    except Exception as exc:
        raise SmsCaptchaError("invalid captcha token") from exc

    expected_sig = _sign_payload(secret, payload)
    if not hmac.compare_digest(expected_sig, signature):
        raise SmsCaptchaError("invalid captcha token")

    parts = payload.split("|")
    if len(parts) != 4:
        raise SmsCaptchaError("invalid captcha token")
    kind, target_s, exp_s, nonce = parts
    if kind != _CAPTCHA_KIND:
        raise SmsCaptchaError("invalid captcha token")
    try:
        target_bp = int(target_s)
        exp = int(exp_s)
    except ValueError as exc:
        raise SmsCaptchaError("invalid captcha token") from exc

    if int(time.time()) > exp:
        raise SmsCaptchaError("captcha expired; request a new one")

    if abs(submitted_bp - target_bp) > _tolerance_bp(config):
        raise SmsCaptchaError("slider position incorrect; try again")

    if consume:
        with _NONCE_LOCK:
            _prune_used_nonces()
            if nonce in _USED_NONCES:
                raise SmsCaptchaError("captcha already used; request a new one")
            _USED_NONCES[nonce] = float(exp)


def reset_sms_captcha_nonces_for_tests() -> None:
    """Test helper — clear one-time nonce cache."""
    with _NONCE_LOCK:
        _USED_NONCES.clear()
