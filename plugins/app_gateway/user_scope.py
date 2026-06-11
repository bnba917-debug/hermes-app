"""Per-user Hermes home — isolates skills, skill snapshots, and skill_manage writes."""

from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path
from typing import Iterator, Optional

import yaml

from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.session_keys import build_gateway_session_key

logger = logging.getLogger(__name__)

_USER_ID_SAFE = re.compile(r"[^a-zA-Z0-9._@-]+")
_MAX_USER_DIR_LEN = 120
_WORKSPACE_DIRNAME = "workspace"
_WORKSPACE_README = """# App user workspace

Files created by Hermes file tools (`read_file`, `write_file`, `patch`, `search_files`)
for this account are resolved relative to this directory only.

Do not store secrets here — use the user's private `.env` at the profile root.
"""


def sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    uid = _USER_ID_SAFE.sub("_", uid)
    if len(uid) > _MAX_USER_DIR_LEN:
        import hashlib

        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]
        uid = f"{uid[:80]}-{digest}"
    return uid


def _lift_operator_root(path: Path) -> Path:
    """If ``path`` is scoped under ``.../app_gateway/users/<id>``, return operator root."""
    parts = path.resolve().parts
    lower = [p.lower() for p in parts]
    for i, name in enumerate(lower):
        if name == "app_gateway" and i + 1 < len(lower) and lower[i + 1] == "users":
            return Path(*parts[:i]) if i > 0 else path
    return path


def operator_hermes_root() -> Path:
    """Operator ``HERMES_HOME`` — never the per-user context override."""
    from hermes_constants import get_default_hermes_root

    return _lift_operator_root(get_default_hermes_root())


def operator_app_gateway_root() -> Path:
    """Shared gateway state (registry, audit, skill caches) — not per-user trees."""
    return operator_hermes_root() / "app_gateway"


def user_hermes_home(user_id: str) -> Path:
    """``~/.hermes/app_gateway/users/<user_id>/`` — workspace + legacy file skills."""
    safe = sanitize_user_id(user_id)
    return operator_app_gateway_root() / "users" / safe


def user_workspace(user_id: str) -> Path:
    """Per-user sandbox for file tools (local disk or MinIO-backed cache)."""
    from plugins.app_gateway.workspace_backend import get_workspace_backend

    root = get_workspace_backend().local_root(user_id)
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.is_file():
        readme.write_text(_WORKSPACE_README, encoding="utf-8")
    return root


def ensure_user_home(user_id: str, *, include_global_skills: bool = True) -> Path:
    """Create user tree; with PostgreSQL, config/skills live in DB + shared caches."""
    home = user_hermes_home(user_id)
    home.mkdir(parents=True, exist_ok=True)
    workspace = user_workspace(user_id)

    postgres_mode = _use_postgres_user_data()
    cfg_path = home / "config.yaml"
    if postgres_mode:
        from plugins.app_gateway.user_data_store import ensure_user_profile

        ensure_user_profile(user_id)
    elif not cfg_path.is_file():
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "model": {
                        "provider": "openrouter",
                        "default": "",
                        "api_key_env": "OPENROUTER_API_KEY",
                    },
                    "skills": {"disabled": []},
                    "terminal": {"cwd": str(workspace)},
                    "approvals": {"mode": "off"},
                    "delegation": {
                        "max_concurrent_children": 3,
                        "orchestrator_enabled": False,
                        "subagent_auto_approve": True,
                    },
                    "app_gateway": {"user_id": sanitize_user_id(user_id)},
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        from plugins.app_gateway.user_credentials import scaffold_user_credentials

        scaffold_user_credentials(home)
        _merge_app_user_config_defaults(cfg_path)

    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    if include_global_skills:
        _link_global_skills_catalog(home, skills_dir, user_id=user_id)

    _apply_shared_skills_catalog(home, user_id=user_id)
    _apply_public_db_skills_catalog(home, user_id=user_id)

    return home


def _use_postgres_user_data() -> bool:
    try:
        from plugins.app_gateway.user_data_store import use_postgres_user_data

        return use_postgres_user_data()
    except Exception:
        return False


def _apply_public_db_skills_catalog(home: Path, *, user_id: str) -> None:
    """Expose operator-published DB public skills via ``public-skills/``."""
    try:
        from plugins.app_gateway.config import load_app_gateway_config
        from plugins.app_gateway.skill_catalog_cache import (
            should_sync_public_catalog,
            skills_catalog_fingerprint,
        )
        from plugins.app_gateway.skill_files import public_skills_root
        from plugins.app_gateway.skill_registry import get_skill_registry
        from plugins.app_gateway.skills_service import merge_shared_skills_into_user_config

        cfg = load_app_gateway_config()
        if not cfg.postgres_url:
            return
        registry = get_skill_registry()
        meta = registry.list_skills(
            visibility="public",
            include_disabled=False,
            include_body=False,
            include_files=False,
        )
        if should_sync_public_catalog(skills_catalog_fingerprint(meta)):
            from plugins.app_gateway.skill_files import sync_public_skills_catalog

            sync_public_skills_catalog(
                registry.list_skills(
                    visibility="public",
                    include_disabled=False,
                    include_body=True,
                    include_files=True,
                )
            )
        merge_shared_skills_into_user_config(
            home,
            public_skills_root(),
            user_id=user_id,
        )
    except Exception as exc:
        logger.debug("public DB skills catalog skipped for %s: %s", home, exc)


def _apply_shared_skills_catalog(home: Path, *, user_id: str) -> None:
    """Merge operator-maintained shared skills into this user's ``external_dirs``."""
    try:
        from plugins.app_gateway.config import load_app_gateway_config
        from plugins.app_gateway.skills_service import (
            ensure_operational_shared_skills_dir,
            merge_shared_skills_into_user_config,
        )

        cfg = load_app_gateway_config()
        if not cfg.enable_shared_skills:
            return
        shared = ensure_operational_shared_skills_dir(cfg.shared_skills_dir)
        merge_shared_skills_into_user_config(home, shared, user_id=user_id)
    except Exception as exc:
        logger.debug("shared skills catalog skipped for %s: %s", home, exc)


def _merge_app_user_config_defaults(cfg_path: Path) -> None:
    """Ensure per-user config has App-friendly delegation/approval defaults."""
    if not cfg_path.is_file():
        return
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return
        approvals = raw.get("approvals")
        if not isinstance(approvals, dict):
            approvals = {}
        if not str(approvals.get("mode") or "").strip():
            approvals["mode"] = "off"
        raw["approvals"] = approvals
        delegation = raw.get("delegation")
        if not isinstance(delegation, dict):
            delegation = {}
        delegation.setdefault("max_concurrent_children", 3)
        delegation.setdefault("orchestrator_enabled", False)
        delegation.setdefault("subagent_auto_approve", True)
        raw["delegation"] = delegation
        cfg_path.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("merge app user config defaults skipped: %s", exc)


def _try_link_bundled_skills(link: Path, bundled: Path) -> bool:
    """Symlink or Windows junction ``link`` → ``bundled``."""
    if link.exists():
        return True
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(bundled, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name == "nt":
        import subprocess

        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(bundled.resolve())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0:
            return True
        logger.debug("mklink /J failed for %s: %s", link, proc.stderr.strip())
    return False


def _link_global_skills_catalog(
    home: Path,
    skills_dir: Path,
    *,
    user_id: Optional[str] = None,
) -> None:
    """Expose bundled repo skills as read-only overlay (user skills override by name)."""
    marker = skills_dir / ".global_skills_linked"
    if marker.is_file():
        return
    try:
        repo_root = Path(__file__).resolve().parents[2]
        bundled = repo_root / "skills"
        if not bundled.is_dir():
            return
        link = skills_dir / "_bundled"
        if link.exists():
            marker.touch()
            return
        if _try_link_bundled_skills(link, bundled):
            marker.write_text(str(bundled), encoding="utf-8")
            return
        _merge_external_skill_dir(home, bundled, user_id=user_id)
        logger.debug("Could not link bundled skills for %s; using external_dirs", home)
    except OSError as exc:
        _merge_external_skill_dir(home, bundled, user_id=user_id)
        logger.debug("Could not link bundled skills for %s: %s", home, exc)


def _merge_external_skill_dir(
    home: Path,
    external_dir: Path,
    *,
    user_id: Optional[str] = None,
) -> None:
    """Add a read-only skills directory to ``skills.external_dirs``."""
    if not external_dir.is_dir():
        return
    if _use_postgres_user_data() and user_id:
        from plugins.app_gateway.user_config_bridge import merge_external_skill_dir_in_profile

        merge_external_skill_dir_in_profile(user_id, external_dir)
        from plugins.app_gateway.user_config_bridge import refresh_user_config_scope

        refresh_user_config_scope(
            user_id,
            home=home,
            workspace=user_workspace(user_id),
        )
        return
    cfg_path = home / "config.yaml"
    if not cfg_path.is_file():
        return
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    skills_cfg = raw.get("skills")
    if not isinstance(skills_cfg, dict):
        skills_cfg = {}
    external_dirs = skills_cfg.get("external_dirs")
    if not isinstance(external_dirs, list):
        external_dirs = []

    target = str(external_dir.resolve())
    existing = {str(Path(x).resolve()) for x in external_dirs if str(x).strip()}
    if target not in existing:
        external_dirs.append(target)
    skills_cfg["external_dirs"] = external_dirs
    raw["skills"] = skills_cfg
    cfg_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@contextlib.contextmanager
def _scoped_terminal_cwd(workspace: Path):
    """Thread-safe cwd for file tools + legacy ``os.environ`` bridge."""
    from gateway.session_context import reset_terminal_cwd, set_terminal_cwd

    ws = str(workspace.resolve())
    cwd_token = set_terminal_cwd(ws)
    prior_env = os.environ.get("TERMINAL_CWD", "_UNSET_")
    os.environ["TERMINAL_CWD"] = ws
    try:
        yield ws
    finally:
        reset_terminal_cwd(cwd_token)
        if prior_env == "_UNSET_":
            os.environ.pop("TERMINAL_CWD", None)
        else:
            os.environ["TERMINAL_CWD"] = prior_env


@contextlib.contextmanager
def app_gateway_user_scope(
    ctx: UserContext,
    *,
    include_global_skills: bool = True,
) -> Iterator[Path]:
    """Set per-task ``HERMES_HOME`` + session context vars for one app user."""
    from gateway.session_context import clear_session_vars, set_session_vars
    from plugins.app_gateway.user_config_bridge import db_user_config_scope, use_db_user_config

    home = ensure_user_home(ctx.user_id, include_global_skills=include_global_skills)
    workspace = user_workspace(ctx.user_id)

    try:
        from plugins.app_gateway.workspace_cache_gc import maybe_prune_workspace_cache

        maybe_prune_workspace_cache(ctx.user_id)
    except Exception:
        pass

    home_token = set_hermes_home_override(home)
    session_tokens = set_session_vars(
        platform="app_gateway",
        user_id=ctx.user_id,
        session_key=build_gateway_session_key(ctx),
        chat_id=ctx.session_id,
        thread_id=ctx.device_id or "",
    )
    config_scope = (
        db_user_config_scope(ctx, home=home, workspace=workspace)
        if use_db_user_config()
        else contextlib.nullcontext()
    )
    try:
        with config_scope, _scoped_terminal_cwd(workspace):
            yield home
    finally:
        reset_hermes_home_override(home_token)
        clear_session_vars(session_tokens)


def clear_user_skills_prompt_cache() -> None:
    """Invalidate skills prompt cache for the active user scope (after skill edits)."""
    from agent.prompt_builder import clear_skills_system_prompt_cache

    clear_skills_system_prompt_cache(clear_snapshot=False)
