"""Session key construction for multi-user isolation (tgs.html memory layer)."""

from __future__ import annotations

import hashlib
import re

from plugins.app_gateway.auth import UserContext

_INVALID = re.compile(r"[\r\n\x00:]")
_MAX_LEN = 200
_SESSION_ID_UNSAFE = re.compile(r"[^a-zA-Z0-9._@-]+")


def _sanitize(part: str) -> str:
    s = (part or "").strip()
    if not s:
        return ""
    if _INVALID.search(s):
        raise ValueError(f"invalid session component: {part!r}")
    if len(s) > _MAX_LEN:
        s = s[:_MAX_LEN]
    return s


def _session_token(part: str) -> str:
    """Safe token for SQLite session ids (no colons — avoids forced hashing)."""
    s = (part or "").strip()
    if not s:
        return "default"
    s = _SESSION_ID_UNSAFE.sub("_", s)
    return s[:80] if len(s) > 80 else s


def build_gateway_session_key(ctx: UserContext) -> str:
    """Stable per-user memory scope for Honcho / long-term memory providers."""
    uid = _sanitize(ctx.user_id)
    sid = _sanitize(ctx.session_id)
    parts = ["agent", "app", uid, "session", sid]
    if ctx.device_id:
        parts.extend(["device", _sanitize(ctx.device_id)])
    return ":".join(parts)


def build_hermes_session_id(ctx: UserContext) -> str:
    """SQLite session id scoped to user — prevents cross-user resume."""
    uid = _session_token(ctx.user_id)
    sid = _session_token(ctx.session_id)
    raw = f"app_{uid}_{sid}"
    if len(raw) <= 64 and not _INVALID.search(raw):
        return raw
    digest = hashlib.sha256(
        f"{ctx.user_id}\0{ctx.session_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"app_{digest}"


def logical_session_id_from_hermes(hermes_session_id: str, user_id: str) -> str:
    """Recover logical session id from a stored Hermes session id."""
    prefix = f"app_{_session_token(user_id)}_"
    sid = hermes_session_id or ""
    if sid.startswith(prefix):
        rest = sid[len(prefix) :]
        return rest or "default"
    return sid
