"""In-process fingerprints to skip redundant DB → disk skill catalog syncs."""

from __future__ import annotations

import hashlib
import threading
from typing import Iterable, Optional

_LOCK = threading.Lock()
_PUBLIC_FP: Optional[str] = None


def skills_catalog_fingerprint(skills: Iterable[dict]) -> str:
    parts: list[str] = []
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("name") or "").strip()
        if not name:
            continue
        parts.append(
            f"{name}:{skill.get('version', 1)}:{skill.get('updated_at', 0)}:{skill.get('status', '')}"
        )
    parts.sort()
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def should_sync_public_catalog(fingerprint: str) -> bool:
    global _PUBLIC_FP
    with _LOCK:
        if _PUBLIC_FP == fingerprint:
            return False
        _PUBLIC_FP = fingerprint
        return True


def invalidate_skill_catalog_cache(*, user_id: str = "") -> None:
    del user_id  # public catalog only; kept for call-site compatibility
    global _PUBLIC_FP
    with _LOCK:
        _PUBLIC_FP = None


def reset_skill_catalog_cache() -> None:
    invalidate_skill_catalog_cache()
