"""Per-user model credentials (isolated ``.env`` — never shared via ``os.environ``)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.user_scope import ensure_user_home, user_hermes_home

logger = logging.getLogger(__name__)

# Provider → env var names in the user's ``.env`` (first match wins).
_PROVIDER_API_KEY_ENVS: Dict[str, List[str]] = {
    "openrouter": ["OPENROUTER_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "kimi-coding": ["KIMI_API_KEY", "KIMI_CODING_API_KEY"],
    "kimi-coding-cn": ["KIMI_CN_API_KEY"],
    "kimi": ["KIMI_API_KEY", "KIMI_CODING_API_KEY"],
    "moonshot-cn": ["KIMI_CN_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "xai": ["XAI_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "fireworks": ["FIREWORKS_API_KEY"],
    "azure-foundry": ["AZURE_FOUNDRY_API_KEY", "AZURE_OPENAI_API_KEY"],
    "moonshot": ["MOONSHOT_API_KEY"],
    "zhipu": ["ZHIPU_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
}

_FALLBACK_KEY_SCAN: List[str] = [
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
]

_BASE_URL_ENVS: Dict[str, List[str]] = {
    "openrouter": ["OPENROUTER_BASE_URL"],
    "openai": ["OPENAI_BASE_URL"],
    "anthropic": ["ANTHROPIC_BASE_URL"],
}


def _model_cfg_dict() -> Dict[str, Any]:
    from hermes_cli.config import load_config

    raw = load_config().get("model")
    if isinstance(raw, dict):
        cfg = dict(raw)
        if not cfg.get("default") and cfg.get("model"):
            cfg["default"] = cfg["model"]
        return cfg
    if isinstance(raw, str) and raw.strip():
        return {"default": raw.strip()}
    return {}


def resolve_user_model() -> str:
    """Model id from the active user's ``config.yaml`` (call inside user scope)."""
    cfg = _model_cfg_dict()
    return (cfg.get("default") or cfg.get("model") or "").strip()


def _pick_api_key(env_vars: Dict[str, str], model_cfg: Dict[str, Any]) -> str:
    explicit = (model_cfg.get("api_key_env") or "").strip()
    if explicit:
        return (env_vars.get(explicit) or "").strip()
    provider = str(model_cfg.get("provider") or "auto").strip().lower()
    for key in _PROVIDER_API_KEY_ENVS.get(provider, _FALLBACK_KEY_SCAN):
        val = (env_vars.get(key) or "").strip()
        if val and val not in ("***", "changeme"):
            return val
    return ""


def _pick_base_url(env_vars: Dict[str, str], model_cfg: Dict[str, Any]) -> str:
    cfg_url = (model_cfg.get("base_url") or "").strip()
    if cfg_url:
        return cfg_url
    provider = str(model_cfg.get("provider") or "auto").strip().lower()
    for key in _BASE_URL_ENVS.get(provider, []):
        val = (env_vars.get(key) or "").strip()
        if val:
            return val
    return (env_vars.get("OPENAI_BASE_URL") or env_vars.get("OPENROUTER_BASE_URL") or "").strip()


def user_credentials_status() -> Dict[str, Any]:
    """Non-secret summary for API responses (inside user scope)."""
    from hermes_constants import get_env_path, get_hermes_home

    model_cfg = _model_cfg_dict()
    env_vars = _load_user_env_file()
    api_key = _pick_api_key(env_vars, model_cfg)
    key_env = (model_cfg.get("api_key_env") or "").strip()
    if not key_env and api_key:
        provider = str(model_cfg.get("provider") or "auto").strip().lower()
        for candidate in _PROVIDER_API_KEY_ENVS.get(provider, _FALLBACK_KEY_SCAN):
            if (env_vars.get(candidate) or "").strip() == api_key:
                key_env = candidate
                break
    return {
        "hermes_home": str(get_hermes_home()),
        "env_path": str(get_env_path()),
        "provider": model_cfg.get("provider") or "auto",
        "model": resolve_user_model(),
        "base_url": _pick_base_url(env_vars, model_cfg) or None,
        "api_key_configured": bool(api_key),
        "api_key_env": key_env or None,
    }


def _load_user_env_file() -> Dict[str, str]:
    from hermes_cli.config import load_env

    return load_env()


def resolve_user_runtime_kwargs(
    *,
    fallback_global: bool = False,
) -> Dict[str, Any]:
    """Build ``AIAgent`` runtime kwargs from this user's ``.env`` + ``config.yaml``.

    Must run inside :func:`app_gateway_user_scope` so paths resolve to the user tree.
    Credentials are passed as ``explicit_*`` so concurrent users do not read
    each other's keys from process-global ``os.environ``.
    """
    from gateway.run import _resolve_runtime_agent_kwargs

    model_cfg = _model_cfg_dict()
    env_vars = _load_user_env_file()
    api_key = _pick_api_key(env_vars, model_cfg)
    base_url = _pick_base_url(env_vars, model_cfg)
    provider = str(model_cfg.get("provider") or "").strip() or None

    if not api_key and fallback_global:
        return _resolve_runtime_agent_kwargs()

    if not api_key:
        from hermes_cli.auth import AuthError
        from hermes_cli.runtime_provider import format_runtime_provider_error
        from hermes_constants import get_hermes_home

        raise RuntimeError(
            format_runtime_provider_error(
                AuthError(
                    "No API key for this user. Add keys to "
                    f"{get_hermes_home()}/.env "
                    "(e.g. OPENROUTER_API_KEY=...) or call PUT /v1/me/inference."
                )
            )
        )

    from hermes_cli.runtime_provider import resolve_runtime_provider

    try:
        runtime = resolve_runtime_provider(
            requested=provider,
            explicit_api_key=api_key,
            explicit_base_url=base_url or None,
            target_model=resolve_user_model() or None,
        )
    except Exception as exc:
        from hermes_cli.runtime_provider import format_runtime_provider_error

        raise RuntimeError(format_runtime_provider_error(exc)) from exc

    return {
        "api_key": runtime.get("api_key"),
        "base_url": runtime.get("base_url"),
        "provider": runtime.get("provider"),
        "api_mode": runtime.get("api_mode"),
        "command": runtime.get("command"),
        "args": list(runtime.get("args") or []),
        "credential_pool": runtime.get("credential_pool"),
    }


def set_user_inference_config(
    ctx: UserContext,
    *,
    api_key: Optional[str] = None,
    api_key_env: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist per-user model settings (DB or filesystem depending on backend)."""
    from plugins.app_gateway.user_scope import app_gateway_user_scope, user_workspace

    ensure_user_home(ctx.user_id)
    home = user_hermes_home(ctx.user_id)
    workspace = user_workspace(ctx.user_id)

    with app_gateway_user_scope(ctx, include_global_skills=False):
        if _use_postgres_user_data():
            from plugins.app_gateway.user_config_bridge import save_user_config_and_secrets
            from plugins.app_gateway.user_data_store import load_user_profile_config, load_user_profile_env

            cfg = load_user_profile_config(ctx.user_id)
            env_secrets = dict(load_user_profile_env(ctx.user_id))
            if not isinstance(cfg.get("model"), dict):
                cfg["model"] = {}
            model_section = dict(cfg["model"])
            if api_key is not None:
                key_name = (api_key_env or model_section.get("api_key_env") or "").strip()
                if not key_name:
                    prov = (provider or model_section.get("provider") or "openrouter").strip().lower()
                    key_name = _PROVIDER_API_KEY_ENVS.get(prov, ["OPENROUTER_API_KEY"])[0]
                env_secrets[key_name] = api_key.strip()
                if api_key_env is None:
                    api_key_env = key_name
            if provider is not None:
                model_section["provider"] = provider.strip()
            if model is not None:
                model_section["default"] = model.strip()
            if base_url is not None:
                model_section["base_url"] = base_url.strip()
            if api_key_env is not None:
                model_section["api_key_env"] = api_key_env.strip()
            cfg["model"] = model_section
            approvals = cfg.get("approvals")
            if not isinstance(approvals, dict):
                approvals = {}
            approvals["mode"] = "off"
            cfg["approvals"] = approvals
            save_user_config_and_secrets(
                ctx.user_id,
                config=cfg,
                env_secrets=env_secrets,
                home=home,
                workspace=workspace,
            )
        else:
            from hermes_cli.config import load_config, save_config, save_env_value

            if api_key is not None:
                model_cfg = _model_cfg_dict()
                key_name = (api_key_env or model_cfg.get("api_key_env") or "").strip()
                if not key_name:
                    prov = (provider or model_cfg.get("provider") or "openrouter").strip().lower()
                    key_name = _PROVIDER_API_KEY_ENVS.get(prov, ["OPENROUTER_API_KEY"])[0]
                save_env_value(key_name, api_key.strip())
                if api_key_env is None:
                    api_key_env = key_name

            cfg = load_config()
            if not isinstance(cfg.get("model"), dict):
                cfg["model"] = {}
            model_section = dict(cfg["model"])
            if provider is not None:
                model_section["provider"] = provider.strip()
            if model is not None:
                model_section["default"] = model.strip()
            if base_url is not None:
                model_section["base_url"] = base_url.strip()
            if api_key_env is not None:
                model_section["api_key_env"] = api_key_env.strip()
            cfg["model"] = model_section
            approvals = cfg.get("approvals")
            if not isinstance(approvals, dict):
                approvals = {}
            approvals["mode"] = "off"
            cfg["approvals"] = approvals
            save_config(cfg)

        status = user_credentials_status()
        if status.get("api_key_configured") and (status.get("model") or "").strip():
            from plugins.app_gateway.user_registry import get_user_registry

            get_user_registry().mark_initialized(ctx.user_id)
        return status


def _use_postgres_user_data() -> bool:
    try:
        from plugins.app_gateway.user_data_store import use_postgres_user_data

        return use_postgres_user_data()
    except Exception:
        return False


def scaffold_user_credentials(home) -> None:
    env_path = home / ".env"
    example = home / ".env.example"
    if not example.is_file():
        example.write_text(
            "# Copy to .env and set your key (never commit .env)\n"
            "OPENROUTER_API_KEY=\n"
            "# OPENAI_API_KEY=\n"
            "# ANTHROPIC_API_KEY=\n",
            encoding="utf-8",
        )
    cfg_path = home / "config.yaml"
    if cfg_path.is_file():
        return
    # ensure_user_home already writes minimal config; extend model block on first credential set
