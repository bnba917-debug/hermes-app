"""Chat file uploads into per-user workspace (for agent read_file)."""

from __future__ import annotations

import re
import secrets
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.user_scope import ensure_user_home, user_workspace

MAX_CHAT_ATTACHMENT_BYTES = 10 * 1024 * 1024
TEXT_INLINE_MAX_BYTES = 48 * 1024

_IMAGE_MIMES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
    }
)

_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".tsv",
        ".xml",
        ".html",
        ".htm",
        ".log",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".cs",
        ".sql",
        ".sh",
        ".bat",
        ".ps1",
        ".env",
        ".ini",
        ".toml",
        ".cfg",
    }
)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    raw = unicodedata.normalize("NFKC", (name or "upload").strip())
    raw = raw.replace("\\", "/").split("/")[-1]
    if not raw or raw in {".", ".."}:
        raw = "upload"
    base = _SAFE_NAME.sub("_", raw).strip("._")
    if not base:
        base = "upload"
    return base[:120]


def _is_image(filename: str, mime: str) -> bool:
    m = (mime or "").split(";")[0].strip().lower()
    if m in _IMAGE_MIMES or m.startswith("image/"):
        return True
    ext = Path(filename).suffix.lower()
    return ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _is_text_candidate(filename: str, mime: str) -> bool:
    m = (mime or "").split(";")[0].strip().lower()
    if m.startswith("text/"):
        return True
    if m in {"application/json", "application/xml", "application/yaml"}:
        return True
    return Path(filename).suffix.lower() in _TEXT_EXTENSIONS


def _decode_text_preview(data: bytes) -> Optional[str]:
    if len(data) > TEXT_INLINE_MAX_BYTES:
        return None
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def store_chat_attachment(
    ctx: UserContext,
    *,
    file_bytes: bytes,
    filename: str,
    mime_type: str = "",
) -> Dict[str, Any]:
    """Save upload under ``workspace/uploads/`` and return metadata for the client."""
    if not file_bytes:
        raise ValueError("empty file")
    if len(file_bytes) > MAX_CHAT_ATTACHMENT_BYTES:
        raise ValueError(
            f"file too large (max {MAX_CHAT_ATTACHMENT_BYTES // (1024 * 1024)} MB)"
        )

    safe_name = _sanitize_filename(filename)
    mime = (mime_type or "").strip().lower()
    ensure_user_home(ctx.user_id, include_global_skills=False)
    workspace = user_workspace(ctx.user_id)
    uploads = workspace / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    token = secrets.token_hex(4)
    dest_name = f"{token}_{safe_name}"
    dest = uploads / dest_name
    dest.write_bytes(file_bytes)

    rel_path = f"uploads/{dest_name}"
    from plugins.app_gateway.workspace_sync import sync_workspace_bytes

    sync_workspace_bytes(ctx.user_id, rel_path, file_bytes)
    kind = "image" if _is_image(safe_name, mime) else "file"
    payload: Dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "path": rel_path,
        "filename": safe_name,
        "stored_name": dest_name,
        "size": len(file_bytes),
        "mime_type": mime or "application/octet-stream",
    }

    if kind == "file" and _is_text_candidate(safe_name, mime):
        preview = _decode_text_preview(file_bytes)
        if preview is not None:
            payload["inline_text"] = preview
            payload["kind"] = "text"

    return payload
