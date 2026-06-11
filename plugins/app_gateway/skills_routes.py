"""Per-user skill listing and cache invalidation (no cross-user sharing)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.skill_scope import classify_skill_scope
from plugins.app_gateway.user_scope import app_gateway_user_scope

logger = logging.getLogger(__name__)


def _skill_category(fm: dict, skill_file: Path, skills_dir: Path) -> str:
    raw = str(fm.get("category") or "").strip()
    if raw:
        return raw
    meta = fm.get("metadata")
    if isinstance(meta, dict):
        hermes = meta.get("hermes")
        if isinstance(hermes, dict):
            tagged = str(hermes.get("category") or "").strip()
            if tagged:
                return tagged
    rel_parts = skill_file.relative_to(skills_dir).parts
    if rel_parts and rel_parts[0] == "_bundled":
        rel_parts = rel_parts[1:]
    if len(rel_parts) >= 2:
        return rel_parts[0]
    tags = fm.get("tags")
    if isinstance(tags, list) and tags:
        return str(tags[0])
    return "其他"


def list_user_skills(ctx: UserContext, *, include_global: bool = True) -> List[Dict[str, Any]]:
    """List skills visible to this user (user dir first, then external/bundled)."""
    from agent.skill_utils import get_all_skills_dirs, parse_frontmatter

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    with app_gateway_user_scope(ctx, include_global_skills=include_global):
        from agent.skill_utils import iter_skill_index_files, get_disabled_skill_names

        disabled = set(get_disabled_skill_names())
        for skills_dir in get_all_skills_dirs():
            if not skills_dir.is_dir():
                continue
            for skill_file in iter_skill_index_files(skills_dir, "SKILL.md"):
                try:
                    raw = skill_file.read_text(encoding="utf-8")
                    fm, _ = parse_frontmatter(raw)
                except Exception:
                    continue
                name = str(fm.get("name") or skill_file.parent.name)
                if name in seen:
                    continue
                seen.add(name)
                rel = str(skill_file.relative_to(skills_dir))
                scope = classify_skill_scope(skill_file.parent, user_id=ctx.user_id)
                category = _skill_category(fm, skill_file, skills_dir)
                out.append(
                    {
                        "name": name,
                        "description": (fm.get("description") or "")[:120],
                        "path": rel,
                        "scope": scope,
                        "category": category,
                        "disabled": name in disabled,
                        "skills_dir": str(skills_dir),
                    }
                )
        try:
            from plugins.app_gateway.skill_registry import get_skill_registry

            for skill in get_skill_registry().list_skills(
                visibility="public",
                include_files=True,
            ):
                name = str(skill.get("name") or "")
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(
                    {
                        "name": name,
                        "description": (skill.get("description") or "")[:120],
                        "path": f"db://public/{name}",
                        "scope": "public",
                        "category": str(skill.get("category") or "公共"),
                        "disabled": name in disabled,
                        "skills_dir": "db://public",
                        "version": skill.get("version"),
                        "file_count": len((skill.get("files") or {})),
                    }
                )
        except Exception as exc:
            logger.debug("DB public skills unavailable for %s: %s", ctx.user_id, exc)
    return sorted(out, key=lambda x: x["name"])


def reload_user_skills(ctx: UserContext) -> Dict[str, Any]:
    from plugins.app_gateway.skill_catalog_cache import invalidate_skill_catalog_cache
    from plugins.app_gateway.skills_service import reload_user_skills_full

    invalidate_skill_catalog_cache(user_id=ctx.user_id)
    return reload_user_skills_full(ctx)
