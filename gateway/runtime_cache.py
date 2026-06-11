"""Cached gateway config + provider resolution for AIAgent construction.

Avoids re-reading config.yaml and re-resolving credentials on every HTTP
request / chat turn.  Invalidated when ``config.yaml`` mtime changes.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_config_token: int = -1
_kit: Optional["GatewayAgentKit"] = None


@dataclass
class GatewayAgentKit:
    """Config-derived agent inputs (cached). Credentials are resolved separately."""

    model: str
    user_config: Dict[str, Any]
    reasoning_config: Optional[Dict[str, Any]]
    fallback_model: Any
    toolsets_by_platform: Dict[str, Tuple[str, ...]]


def get_gateway_runtime_kwargs() -> Dict[str, Any]:
    """Fresh provider credentials (not cached — keys may change without config mtime)."""
    from gateway.run import _resolve_runtime_agent_kwargs

    return _resolve_runtime_agent_kwargs()


def _config_mtime_token() -> int:
    try:
        from hermes_cli.config import get_config_path

        path = get_config_path()
        return path.stat().st_mtime_ns if path.exists() else 0
    except Exception:
        return 0


def invalidate_gateway_agent_kit() -> None:
    """Drop cached kit (config reload, tests)."""
    global _kit, _config_token
    with _lock:
        _kit = None
        _config_token = -1


def get_gateway_agent_kit(*, platform: str) -> GatewayAgentKit:
    """Return cached agent-creation inputs for a messaging platform."""
    global _kit, _config_token
    token = _config_mtime_token()
    with _lock:
        if _kit is not None and token == _config_token:
            return _kit

        from gateway.run import (
            GatewayRunner,
            _load_gateway_config,
            _resolve_gateway_model,
        )
        from hermes_cli.tools_config import _get_platform_tools

        user_config = _load_gateway_config()
        kit = GatewayAgentKit(
            model=_resolve_gateway_model(user_config),
            user_config=user_config,
            reasoning_config=GatewayRunner._load_reasoning_config(),
            fallback_model=GatewayRunner._load_fallback_model(),
            toolsets_by_platform={},
        )
        # Pre-warm common platforms used by gateway surfaces.
        for plat in ("api_server", "app_gateway", "messaging", "telegram", "discord"):
            try:
                kit.toolsets_by_platform[plat] = tuple(
                    sorted(_get_platform_tools(user_config, plat))
                )
            except Exception:
                kit.toolsets_by_platform[plat] = ()

        try:
            kit.toolsets_by_platform[platform] = tuple(
                sorted(_get_platform_tools(user_config, platform))
            )
        except Exception as exc:
            logger.debug("toolsets for %s: %s", platform, exc)
            kit.toolsets_by_platform[platform] = ()

        _kit = kit
        _config_token = token
        return _kit


def toolsets_for_platform(platform: str) -> Tuple[str, ...]:
    kit = get_gateway_agent_kit(platform=platform)
    cached = kit.toolsets_by_platform.get(platform)
    if cached is not None:
        return cached
    from hermes_cli.tools_config import _get_platform_tools

    with _lock:
        cached = tuple(sorted(_get_platform_tools(kit.user_config, platform)))
        kit.toolsets_by_platform[platform] = cached
        return cached


_insights_engine: Any = None


def get_insights_engine():
    """Process-wide InsightsEngine backed by the shared session store."""
    global _insights_engine
    with _lock:
        if _insights_engine is None:
            from agent.insights import InsightsEngine
            from hermes_state import get_shared_session_db

            _insights_engine = InsightsEngine(get_shared_session_db())
        return _insights_engine
