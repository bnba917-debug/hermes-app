"""JWT validation (HS256) using stdlib only — no PyJWT dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


class JwtError(ValueError):
    """Invalid or expired JWT."""


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def verify_hs256_jwt(token: str, secret: str, *, leeway: int = 30) -> Dict[str, Any]:
    """Verify an HS256 JWT and return the payload claims dict."""
    if not token or not secret:
        raise JwtError("missing token or secret")
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtError("malformed token")
    header_b, payload_b, sig_b = parts
    try:
        header = json.loads(_b64url_decode(header_b))
        payload = json.loads(_b64url_decode(payload_b))
    except (json.JSONDecodeError, ValueError) as exc:
        raise JwtError("invalid encoding") from exc

    alg = header.get("alg")
    if alg != "HS256":
        raise JwtError(f"unsupported algorithm: {alg!r}")

    signing_input = f"{header_b}.{payload_b}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(sig_b)
    except ValueError as exc:
        raise JwtError("invalid signature encoding") from exc
    if not hmac.compare_digest(expected, actual):
        raise JwtError("signature mismatch")

    now = int(time.time())
    exp = payload.get("exp")
    if exp is not None:
        try:
            if int(exp) < now - leeway:
                raise JwtError("token expired")
        except (TypeError, ValueError) as exc:
            raise JwtError("invalid exp") from exc
    nbf = payload.get("nbf")
    if nbf is not None:
        try:
            if int(nbf) > now + leeway:
                raise JwtError("token not yet valid")
        except (TypeError, ValueError) as exc:
            raise JwtError("invalid nbf") from exc

    return payload


def encode_hs256_jwt(payload: Dict[str, Any], secret: str) -> str:
    """Encode a JWT (for tests and dev tokens)."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_b = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b}.{payload_b}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b}.{payload_b}.{_b64url_encode(sig)}"


@dataclass(frozen=True)
class UserContext:
    user_id: str
    session_id: str
    device_id: Optional[str]
    raw_claims: Dict[str, Any]


def extract_user_context(
    claims: Dict[str, Any],
    *,
    claim_user_id: str = "sub",
    claim_session_id: str = "session_id",
    claim_device_id: str = "device_id",
    fallback_session_id: str = "default",
) -> UserContext:
    """Map JWT claims to Hermes user context."""
    user_id = str(claims.get(claim_user_id) or claims.get("user_id") or "").strip()
    if not user_id:
        raise JwtError(f"missing claim {claim_user_id!r}")
    session_id = str(claims.get(claim_session_id) or fallback_session_id).strip() or fallback_session_id
    device_raw = claims.get(claim_device_id)
    device_id = str(device_raw).strip() if device_raw else None
    return UserContext(
        user_id=user_id,
        session_id=session_id,
        device_id=device_id,
        raw_claims=claims,
    )


def parse_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
