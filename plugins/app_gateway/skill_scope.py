"""Classify app-gateway skills into 内置 / 公共 / 我的 / 共享."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

_SCOPE_BUNDLED = "_bundled"


@lru_cache(maxsize=1)
def _repo_bundled_skills_root() -> Optional[Path]:
    """Shipped repo ``skills/`` tree (Windows may mount via ``external_dirs``)."""
    try:
        root = Path(__file__).resolve().parents[2] / "skills"
        return root.resolve() if root.is_dir() else None
    except OSError:
        return None


@lru_cache(maxsize=1)
def _shared_skills_root() -> Optional[Path]:
    from plugins.app_gateway.user_scope import operator_app_gateway_root

    root = operator_app_gateway_root() / "shared-skills"
    try:
        return root.resolve() if root.is_dir() else None
    except OSError:
        return None


def classify_skill_scope(skill_dir: Path, *, user_id: str) -> str:
    """Return ``bundled_readonly``, ``public``, ``user``, or ``shared``."""
    from plugins.app_gateway.skill_files import public_skills_root
    from plugins.app_gateway.user_scope import user_hermes_home

    root = skill_dir.resolve()
    if _SCOPE_BUNDLED in root.parts:
        return "bundled_readonly"

    bundled_root = _repo_bundled_skills_root()
    if bundled_root is not None:
        try:
            root.relative_to(bundled_root)
            return "bundled_readonly"
        except (ValueError, OSError):
            pass

    try:
        root.relative_to(public_skills_root().resolve())
        return "public"
    except (ValueError, OSError):
        pass

    shared_root = _shared_skills_root()
    if shared_root is not None:
        try:
            root.relative_to(shared_root)
            return "shared"
        except (ValueError, OSError):
            pass

    try:
        skill_root = (user_hermes_home(user_id) / "skills").resolve()
        rel = root.relative_to(skill_root)
        if _SCOPE_BUNDLED not in rel.parts:
            return "user"
    except (ValueError, OSError):
        pass

    return "shared"
