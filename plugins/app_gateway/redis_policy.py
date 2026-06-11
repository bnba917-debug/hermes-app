"""Production Redis requirements for multi-tenant App Gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.redis_store import SessionHotCache


class RedisRequiredError(RuntimeError):
    """Raised when production mode requires Redis but it is missing or unreachable."""


def require_redis_for_production(config: AppGatewayConfig) -> bool:
    """True when Redis must be configured and reachable (multi-tenant production)."""
    if bool(getattr(config, "require_redis", False)):
        return True
    if bool(getattr(config, "postgres_only", False)):
        return True
    try:
        from plugins.app_gateway.postgres_policy import load_postgres_only_flag

        if load_postgres_only_flag():
            return True
    except Exception:
        pass
    return False


def validate_app_gateway_redis(config: AppGatewayConfig, cache: SessionHotCache) -> None:
    """Fail fast at startup when production policy requires Redis."""
    if not require_redis_for_production(config):
        return
    url = str(getattr(config, "redis_url", "") or "").strip()
    if not url:
        raise RedisRequiredError(
            "Multi-tenant production requires redis_url "
            "(set app_gateway.redis_url or APP_GATEWAY_REDIS_URL)"
        )
    if not cache.available:
        raise RedisRequiredError(
            f"Redis is required but unreachable at {url!r}. "
            "Fix connectivity before starting the gateway."
        )
