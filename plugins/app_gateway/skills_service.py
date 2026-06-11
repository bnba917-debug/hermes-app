"""App Gateway skill library — list, reload, disable (per-user scope)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.skill_scope import classify_skill_scope
from plugins.app_gateway.user_scope import (
    app_gateway_user_scope,
    clear_user_skills_prompt_cache,
    user_hermes_home,
    user_workspace,
)

logger = logging.getLogger(__name__)


def _use_postgres_user_data() -> bool:
    try:
        from plugins.app_gateway.user_data_store import use_postgres_user_data

        return use_postgres_user_data()
    except Exception:
        return False


def _after_skill_mutation(ctx: UserContext) -> None:
    """Invalidate caches so the next chat turn sees updated skills."""
    del ctx
    clear_user_skills_prompt_cache()
    try:
        from agent.prompt_builder import clear_skills_system_prompt_cache

        clear_skills_system_prompt_cache(clear_snapshot=True)
    except Exception:
        pass


def reload_user_skills_full(ctx: UserContext) -> Dict[str, Any]:
    """Rescan slash-command map + clear prompt cache; return diff."""
    with app_gateway_user_scope(ctx):
        from agent.skill_commands import reload_skills

        diff = reload_skills()
        _after_skill_mutation(ctx)
    return {
        "ok": True,
        "user_id": ctx.user_id,
        "skills_home": str(user_hermes_home(ctx.user_id) / "skills"),
        "prompt_cache_cleared": True,
        **diff,
    }


def get_user_skill(ctx: UserContext, skill_name: str) -> Dict[str, Any]:
    from agent.skill_utils import parse_frontmatter
    from tools.skill_manager_tool import _find_skill

    with app_gateway_user_scope(ctx):
        hit = _find_skill(skill_name)
        if hit:
            skill_md = hit["path"] / "SKILL.md"
            raw = skill_md.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(raw)
            root = hit["path"]
            scope = classify_skill_scope(root, user_id=ctx.user_id)
            return {
                "name": str(fm.get("name") or skill_name),
                "description": fm.get("description") or "",
                "scope": scope,
                "writable": scope == "user",
                "path": str(root),
                "skill_md": raw,
                "body": body,
            }

    try:
        from plugins.app_gateway.skill_registry import get_skill_registry

        public = get_skill_registry().get_skill(
            skill_name,
            visibility="public",
        )
        if public:
            raw = str(public.get("skill_md") or "")
            fm, body = parse_frontmatter(raw)
            files = public.get("files") if isinstance(public.get("files"), dict) else {}
            from plugins.app_gateway.skill_files import public_skills_root
            from plugins.app_gateway.skill_registry import _slug

            materialized = public_skills_root() / _slug(public.get("name") or skill_name)
            return {
                "name": str(fm.get("name") or public.get("name") or skill_name),
                "description": fm.get("description") or public.get("description") or "",
                "scope": "public",
                "writable": False,
                "path": str(materialized),
                "skill_md": raw,
                "body": body,
                "version": public.get("version"),
                "files": sorted(files.keys()),
            }
    except Exception as exc:
        logger.debug("DB public skill lookup skipped for %s: %s", skill_name, exc)
    raise ValueError(f"skill not found: {skill_name}")


def set_skills_disabled(ctx: UserContext, disabled: List[str]) -> Dict[str, Any]:
    """Replace the user's ``skills.disabled`` list."""
    clean = sorted({str(x).strip() for x in disabled if str(x).strip()})
    with app_gateway_user_scope(ctx):
        if _use_postgres_user_data():
            from plugins.app_gateway.user_config_bridge import save_user_config_and_secrets
            from plugins.app_gateway.user_data_store import load_user_profile_config, load_user_profile_env

            cfg = load_user_profile_config(ctx.user_id)
            skills_cfg = cfg.get("skills")
            if not isinstance(skills_cfg, dict):
                skills_cfg = {}
            skills_cfg["disabled"] = clean
            cfg["skills"] = skills_cfg
            save_user_config_and_secrets(
                ctx.user_id,
                config=cfg,
                env_secrets=load_user_profile_env(ctx.user_id),
                home=user_hermes_home(ctx.user_id),
                workspace=user_workspace(ctx.user_id),
            )
        else:
            from hermes_cli.config import load_config, save_config

            cfg = load_config()
            skills_cfg = cfg.get("skills")
            if not isinstance(skills_cfg, dict):
                skills_cfg = {}
            skills_cfg["disabled"] = clean
            cfg["skills"] = skills_cfg
            save_config(cfg)
        _after_skill_mutation(ctx)
    return {"ok": True, "user_id": ctx.user_id, "disabled": clean}


def get_skills_config(ctx: UserContext) -> Dict[str, Any]:
    from hermes_cli.config import load_config
    from agent.skill_utils import get_disabled_skill_names

    with app_gateway_user_scope(ctx):
        cfg = load_config()
        skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
        return {
            "user_id": ctx.user_id,
            "disabled": sorted(get_disabled_skill_names()),
            "external_dirs": list(skills_cfg.get("external_dirs") or []),
            "skills_home": str(user_hermes_home(ctx.user_id) / "skills"),
            "storage": "postgres" if _use_postgres_user_data() else "files",
        }


def ensure_operational_shared_skills_dir(shared_dir: str) -> Path:
    """Create ``~/.hermes/app_gateway/shared-skills`` if configured path empty."""
    p = Path((shared_dir or "").strip()).expanduser()
    if not p:
        from plugins.app_gateway.user_scope import operator_app_gateway_root

        p = operator_app_gateway_root() / "shared-skills"
    p.mkdir(parents=True, exist_ok=True)
    readme = p / "README.txt"
    if not readme.is_file():
        readme.write_text(
            "Drop skill folders here (each with SKILL.md). "
            "Referenced via app_gateway.shared_skills_dir for all app users.\n",
            encoding="utf-8",
        )
    return p.resolve()


def merge_shared_skills_into_user_config(
    home: Path,
    shared_dir: Path,
    *,
    user_id: Optional[str] = None,
) -> None:
    """Add shared_skills_dir to per-user ``skills.external_dirs`` if missing."""
    if _use_postgres_user_data() and user_id:
        from plugins.app_gateway.user_config_bridge import merge_external_skill_dir_in_profile

        merge_external_skill_dir_in_profile(user_id, shared_dir)
        return
    cfg_path = home / "config.yaml"
    if not cfg_path.is_file():
        return
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    skills_cfg = raw.get("skills")
    if not isinstance(skills_cfg, dict):
        skills_cfg = {}
    ext = skills_cfg.get("external_dirs") or []
    if isinstance(ext, str):
        ext = [ext]
    if not isinstance(ext, list):
        ext = []
    resolved = str(shared_dir.resolve())
    if resolved not in {str(Path(x).expanduser().resolve()) for x in ext if x}:
        ext.append(resolved)
    skills_cfg["external_dirs"] = ext
    raw["skills"] = skills_cfg
    cfg_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
