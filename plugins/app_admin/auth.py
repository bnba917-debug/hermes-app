"""Admin authentication helpers."""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict

from plugins.app_gateway.auth import JwtError, encode_hs256_jwt, verify_hs256_jwt

_ADMIN_ISSUER = "hermes-app-admin"
_ADMIN_AUDIENCE = "hermes-app-admin"


def verify_admin_password(candidate: str, expected: str) -> bool:
    if not expected:
        return False
    return secrets.compare_digest(str(candidate or ""), str(expected))


def issue_admin_token(username: str, secret: str, *, ttl_seconds: int = 8 * 3600) -> str:
    if not secret:
        raise RuntimeError("APP_ADMIN_SESSION_SECRET is required")
    now = int(time.time())
    return encode_hs256_jwt(
        {
            "sub": username,
            "role": "admin",
            "iss": _ADMIN_ISSUER,
            "aud": _ADMIN_AUDIENCE,
            "iat": now,
            "exp": now + ttl_seconds,
        },
        secret,
    )


def verify_admin_token(token: str, secret: str) -> Dict[str, Any]:
    if not secret:
        raise JwtError("APP_ADMIN_SESSION_SECRET is required")
    claims = verify_hs256_jwt(token, secret)
    if claims.get("role") != "admin":
        raise JwtError("admin role required")
    if claims.get("iss") != _ADMIN_ISSUER or claims.get("aud") != _ADMIN_AUDIENCE:
        raise JwtError("admin token audience required")
    return claims
