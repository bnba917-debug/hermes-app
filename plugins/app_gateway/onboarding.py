"""Post-registration: pick model + API key → initialize per-user Hermes home."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.user_credentials import (
    set_user_inference_config,
    user_credentials_status,
)
from plugins.app_gateway.user_registry import get_user_registry
from plugins.app_gateway.user_scope import ensure_user_home

logger = logging.getLogger(__name__)

# Shown in the mobile model picker (override via config ``app_gateway.onboarding_models``).
DEFAULT_ONBOARDING_MODELS: List[Dict[str, str]] = [
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash（官方 API）",
        "provider": "deepseek",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
    },
    {
        "id": "kimi-k2.6",
        "label": "Kimi K2.6（月之暗面 · 国内）",
        "provider": "kimi-coding-cn",
        "api_key_env": "KIMI_CN_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
    },
    {
        "id": "poolside/laguna-m.1:free",
        "label": "Laguna M.1 Free（OpenRouter）",
        "provider": "openrouter",
        "api_key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
    },
]


def resolve_onboarding_entry(
    model: str,
    *,
    provider: Optional[str] = None,
    api_key_env: Optional[str] = None,
    config_models: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Match onboarding catalog entry so provider/key_env align with model id."""
    catalog = list_onboarding_models(config_models)
    for entry in catalog:
        if entry.get("id") == model:
            resolved: Dict[str, str] = {
                "provider": str(entry.get("provider") or provider or "openrouter"),
                "api_key_env": str(entry.get("api_key_env") or api_key_env or ""),
            }
            entry_base = (entry.get("base_url") or "").strip()
            if entry_base:
                resolved["base_url"] = entry_base
            return resolved
    return {
        "provider": str(provider or "openrouter"),
        "api_key_env": str(api_key_env or ""),
    }


def list_onboarding_models(config_models: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    if config_models:
        return list(config_models)
    return [dict(m) for m in DEFAULT_ONBOARDING_MODELS]


def onboarding_status(ctx: UserContext) -> Dict[str, Any]:
    reg = get_user_registry()
    record = reg.get_by_user_id(ctx.user_id)
    initialized = bool(record and record.initialized_at)
    inference: Dict[str, Any] = {}
    try:
        from plugins.app_gateway.user_scope import app_gateway_user_scope

        with app_gateway_user_scope(ctx, include_global_skills=True):
            inference = user_credentials_status()
    except Exception:
        inference = {"api_key_configured": False}

    if (
        not initialized
        and inference.get("api_key_configured")
        and (inference.get("model") or "").strip()
    ):
        try:
            reg.mark_initialized(ctx.user_id)
            initialized = True
        except Exception:
            logger.exception("Failed to auto-mark user %s initialized", ctx.user_id)

    return {
        "user_id": ctx.user_id,
        "phone": mask_phone_from_record(record),
        "initialized": initialized,
        "ready_for_chat": initialized and inference.get("api_key_configured"),
        "inference": inference,
    }


def mask_phone_from_record(record) -> Optional[str]:
    if not record:
        return None
    from plugins.app_gateway.phone_auth import mask_phone

    return mask_phone(record.phone)


def _configured_onboarding_models() -> Optional[List[Dict[str, Any]]]:
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        models = load_app_gateway_config().onboarding_models
        return list(models) if models else None
    except Exception:
        return None


def complete_onboarding(
    ctx: UserContext,
    *,
    api_key: str,
    model: str,
    provider: str = "openrouter",
    api_key_env: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Save model + key, scaffold user home, mark registry initialized."""
    if not (api_key or "").strip():
        raise ValueError("api_key is required")
    if not (model or "").strip():
        raise ValueError("model is required")

    ensure_user_home(ctx.user_id, include_global_skills=True)

    resolved = resolve_onboarding_entry(
        model.strip(),
        provider=provider,
        api_key_env=api_key_env,
        config_models=_configured_onboarding_models(),
    )
    prov = resolved["provider"] or "openrouter"
    env_name = (api_key_env or resolved["api_key_env"] or "").strip()
    if not env_name:
        if prov == "deepseek":
            env_name = "DEEPSEEK_API_KEY"
        elif prov in {"kimi-coding-cn", "kimi-coding", "kimi", "moonshot-cn"}:
            env_name = "KIMI_CN_API_KEY" if prov == "kimi-coding-cn" else "KIMI_API_KEY"
        else:
            env_name = "OPENROUTER_API_KEY"
    resolved_base_url = (base_url or resolved.get("base_url") or "").strip() or None

    inference = set_user_inference_config(
        ctx,
        api_key=api_key.strip(),
        api_key_env=env_name,
        provider=prov,
        model=model.strip(),
        base_url=resolved_base_url,
    )

    get_user_registry().mark_initialized(ctx.user_id)

    logger.info("User %s onboarding complete model=%s", ctx.user_id, model)
    return {
        "ok": True,
        "initialized": True,
        "ready_for_chat": True,
        "user_id": ctx.user_id,
        "inference": inference,
    }
