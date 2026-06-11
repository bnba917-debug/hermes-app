"""Per-user session list and message history for the App Gateway."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.session_keys import (
    build_hermes_session_id,
    logical_session_id_from_hermes,
    _session_token,
)


def _session_prefix(user_id: str) -> str:
    return f"app_{_session_token(user_id)}_"


def _shared_session_db():
    from hermes_state import get_shared_session_db

    return get_shared_session_db()


def list_user_sessions(
    ctx: UserContext,
    *,
    limit: int = 20,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List chat sessions owned by ``ctx.user_id``."""
    db = _shared_session_db()
    prefix = _session_prefix(ctx.user_id)
    rows = db.list_sessions_rich(
        source="app_gateway",
        limit=max(limit + offset, limit) * 4,
        offset=0,
        order_by_last_active=True,
    )
    owned = [
        r
        for r in rows
        if str(r.get("user_id") or "") == ctx.user_id
        or str(r.get("id") or "").startswith(prefix)
    ]
    page = owned[offset : offset + limit]
    out: List[Dict[str, Any]] = []
    for row in page:
        sid = str(row.get("id") or "")
        logical = logical_session_id_from_hermes(sid, ctx.user_id)
        out.append(
            {
                "session_id": logical,
                "hermes_session_id": sid,
                "title": row.get("title") or "",
                "preview": row.get("preview") or "",
                "message_count": row.get("message_count") or 0,
                "last_active": row.get("last_active"),
                "started_at": row.get("started_at"),
            }
        )
    return out


def create_user_session(ctx: UserContext, *, session_id: Optional[str] = None) -> Dict[str, str]:
    """Allocate a new logical session id for this user."""
    logical = (session_id or "").strip() or f"s-{uuid.uuid4().hex[:12]}"
    probe = UserContext(
        user_id=ctx.user_id,
        session_id=logical,
        device_id=ctx.device_id,
        raw_claims=ctx.raw_claims,
    )
    hermes_id = build_hermes_session_id(probe)
    db = _shared_session_db()
    try:
        db.create_session(hermes_id, "app_gateway", user_id=ctx.user_id)
    except Exception:
        pass
    return {"session_id": logical, "hermes_session_id": hermes_id}


def _hermes_id_for_session(ctx: UserContext, logical_session_id: str) -> str:
    probe = UserContext(
        user_id=ctx.user_id,
        session_id=logical_session_id,
        device_id=ctx.device_id,
        raw_claims=ctx.raw_claims,
    )
    hermes_id = build_hermes_session_id(probe)
    prefix = _session_prefix(ctx.user_id)
    if not hermes_id.startswith(prefix) and not hermes_id.startswith("app_"):
        raise ValueError("invalid session_id for this user")
    return hermes_id


def _content_text(content: Any, *, has_tool_calls: bool = False) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
        if has_tool_calls:
            return "（调用了工具）"
        return ""
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                t = str(part.get("text") or "").strip()
                if t:
                    parts.append(t)
            elif part.get("type") == "image_url":
                parts.append("（图片）")
        if parts:
            return "\n".join(parts)
        if has_tool_calls:
            return "（调用了工具）"
    return ""


def _app_message_text(msg: Dict[str, Any]) -> str:
    return _content_text(msg.get("content"), has_tool_calls=bool(msg.get("tool_calls")))


def set_user_session_title(
    ctx: UserContext,
    logical_session_id: str,
    title: str,
) -> Dict[str, Any]:
    """Set display title for a user-owned session."""
    cleaned = (title or "").strip()
    if not cleaned:
        raise ValueError("title is required")
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."
    hermes_id = _hermes_id_for_session(ctx, logical_session_id)
    db = _shared_session_db()
    db.set_session_title(hermes_id, cleaned)
    return {"session_id": logical_session_id, "title": cleaned}


def suggest_user_session_title(
    ctx: UserContext,
    logical_session_id: str,
) -> Dict[str, Any]:
    """AI-generate a short title from the first user/assistant exchange."""
    hermes_id = _hermes_id_for_session(ctx, logical_session_id)
    db = _shared_session_db()
    try:
        existing = db.get_session_title(hermes_id)
        if existing:
            return {"session_id": logical_session_id, "title": existing, "generated": False}
    except Exception:
        pass

    raw = db.get_messages_as_conversation(hermes_id) or []
    user_text = ""
    assistant_text = ""
    for msg in raw:
        role = str(msg.get("role") or "")
        text = _content_text(msg.get("content"))
        if not text:
            continue
        if role == "user" and not user_text:
            user_text = text
        elif role == "assistant" and not assistant_text:
            assistant_text = text
        if user_text and assistant_text:
            break

    if not user_text:
        raise ValueError("no user message to title from")

    # Fallback when assistant reply not persisted yet.
    if not assistant_text:
        fallback = user_text[:40].strip()
        if len(user_text) > 40:
            fallback += "..."
        db.set_session_title(hermes_id, fallback)
        return {"session_id": logical_session_id, "title": fallback, "generated": True}

    from agent.title_generator import generate_title
    from plugins.app_gateway.user_scope import app_gateway_user_scope

    title: Optional[str] = None
    with app_gateway_user_scope(ctx, include_global_skills=False):
        title = generate_title(user_text, assistant_text)
    if not title:
        title = user_text[:40].strip()
        if len(user_text) > 40:
            title += "..."
    db.set_session_title(hermes_id, title)
    return {"session_id": logical_session_id, "title": title, "generated": True}


def get_user_messages(
    ctx: UserContext,
    logical_session_id: str,
) -> List[Dict[str, Any]]:
    """Return OpenAI-format messages for one user session."""
    hermes_id = _hermes_id_for_session(ctx, logical_session_id)
    db = _shared_session_db()
    raw = db.get_messages_as_conversation(hermes_id) or []
    return _to_app_messages(raw)


def _to_app_messages(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip tool/reasoning fields — mobile UI shows user/assistant text only."""
    out: List[Dict[str, Any]] = []
    for msg in raw:
        role = str(msg.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        text = _app_message_text(msg)
        if not text:
            continue
        out.append({"role": role, "content": text})
    return out
