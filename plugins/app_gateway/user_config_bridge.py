"""In-memory user config/env bridge — PostgreSQL profiles without per-user files."""

from __future__ import annotations

import contextlib
import copy
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

from plugins.app_gateway.auth import UserContext


def use_db_user_config() -> bool:
    try:
        from plugins.app_gateway.user_data_store import use_postgres_user_data

        return use_postgres_user_data()
    except Exception:
        return False


def resolve_external_skills_dirs(
    cfg: Dict[str, Any],
    *,
    hermes_home: Path,
) -> List[Path]:
    """Resolve ``skills.external_dirs`` the same way ``skill_utils`` does."""
    from hermes_constants import get_skills_dir

    skills_cfg = cfg.get("skills")
    if not isinstance(skills_cfg, dict):
        return []
    raw_dirs = skills_cfg.get("external_dirs")
    if not raw_dirs:
        return []
    if isinstance(raw_dirs, str):
        raw_dirs = [raw_dirs]
    if not isinstance(raw_dirs, list):
        return []

    local_skills = get_skills_dir().resolve()
    seen: Set[Path] = set()
    result: List[Path] = []
    for entry in raw_dirs:
        entry = str(entry).strip()
        if not entry:
            continue
        expanded = os.path.expanduser(os.path.expandvars(entry))
        p = Path(expanded)
        if not p.is_absolute():
            p = (hermes_home / p).resolve()
        else:
            p = p.resolve()
        if p == local_skills or p in seen:
            continue
        if p.is_dir():
            seen.add(p)
            result.append(p)
    return result


def build_runtime_user_config(
    user_id: str,
    *,
    home: Path,
    workspace: Path,
) -> tuple[Dict[str, Any], Dict[str, str]]:
    from plugins.app_gateway.user_data_store import ensure_user_profile

    profile = ensure_user_profile(user_id)
    cfg = copy.deepcopy(profile.get("config") or {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("app_gateway", {})
    if isinstance(cfg["app_gateway"], dict):
        cfg["app_gateway"]["user_id"] = user_id
    terminal = cfg.get("terminal")
    if not isinstance(terminal, dict):
        terminal = {}
    terminal["cwd"] = str(workspace.resolve())
    cfg["terminal"] = terminal
    env = profile.get("env_secrets") or {}
    env_out = {str(k): str(v) for k, v in env.items() if str(k).strip()}
    return cfg, env_out


def merge_external_skill_dir_in_profile(user_id: str, external_dir: Path) -> None:
    """Append ``external_dir`` to the user's DB-backed ``skills.external_dirs``."""
    from plugins.app_gateway.user_data_store import ensure_user_profile, save_user_profile

    if not external_dir.is_dir():
        return
    profile = ensure_user_profile(user_id)
    cfg = copy.deepcopy(profile.get("config") or {})
    skills_cfg = cfg.get("skills")
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
    cfg["skills"] = skills_cfg
    save_user_profile(
        user_id,
        config=cfg,
        env_secrets=profile.get("env_secrets"),
    )


def apply_app_user_config_defaults(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(cfg)
    approvals = out.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    if not str(approvals.get("mode") or "").strip():
        approvals["mode"] = "off"
    out["approvals"] = approvals
    delegation = out.get("delegation")
    if not isinstance(delegation, dict):
        delegation = {}
    delegation.setdefault("max_concurrent_children", 3)
    delegation.setdefault("orchestrator_enabled", False)
    delegation.setdefault("subagent_auto_approve", True)
    out["delegation"] = delegation
    return out


def install_user_config_scope(
    user_id: str,
    *,
    home: Path,
    workspace: Path,
) -> tuple[Any, Any, Any]:
    """Install in-memory config/env/external_dirs for the active task."""
    from agent.skill_utils import set_external_skills_dirs_override
    from hermes_cli.config import set_user_config_override, set_user_env_override

    cfg, env = build_runtime_user_config(user_id, home=home, workspace=workspace)
    cfg = apply_app_user_config_defaults(cfg)
    config_token = set_user_config_override(cfg)
    env_token = set_user_env_override(env)
    ext_holder: List[Path] = resolve_external_skills_dirs(cfg, hermes_home=home)
    ext_token = set_external_skills_dirs_override(ext_holder)
    return config_token, env_token, ext_token


def clear_user_config_scope(config_token, env_token, ext_token) -> None:
    from agent.skill_utils import reset_external_skills_dirs_override
    from hermes_cli.config import reset_user_config_override, reset_user_env_override

    reset_external_skills_dirs_override(ext_token)
    reset_user_env_override(env_token)
    reset_user_config_override(config_token)


def refresh_user_config_scope(user_id: str, *, home: Path, workspace: Path) -> None:
    """Refresh active scope overrides after a DB profile mutation."""
    from agent.skill_utils import (
        get_external_skills_dirs_override,
        set_external_skills_dirs_override,
    )
    from hermes_cli.config import get_user_config_override, get_user_env_override

    cfg_override = get_user_config_override()
    env_override = get_user_env_override()
    if cfg_override is None and env_override is None:
        return
    cfg, env = build_runtime_user_config(user_id, home=home, workspace=workspace)
    cfg = apply_app_user_config_defaults(cfg)
    if cfg_override is not None:
        cfg_override.clear()
        cfg_override.update(copy.deepcopy(cfg))
    if env_override is not None:
        env_override.clear()
        env_override.update(dict(env))
    ext_override = get_external_skills_dirs_override()
    if ext_override is not None:
        ext_override.clear()
        ext_override.extend(resolve_external_skills_dirs(cfg, hermes_home=home))


def save_user_config_and_secrets(
    user_id: str,
    *,
    config: Dict[str, Any],
    env_secrets: Optional[Dict[str, str]] = None,
    home: Path,
    workspace: Path,
) -> None:
    from plugins.app_gateway.user_data_store import save_user_profile

    save_user_profile(user_id, config=config, env_secrets=env_secrets)
    refresh_user_config_scope(user_id, home=home, workspace=workspace)


@contextlib.contextmanager
def db_user_config_scope(
    ctx: UserContext,
    *,
    home: Path,
    workspace: Path,
) -> Iterator[None]:
    tokens = install_user_config_scope(ctx.user_id, home=home, workspace=workspace)
    try:
        yield
    finally:
        clear_user_config_scope(*tokens)
