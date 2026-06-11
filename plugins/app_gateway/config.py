"""Load ``app_gateway`` settings from config.yaml and environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

import yaml


@dataclass
class AppGatewayConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8787
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    require_jwt: bool = True
    app_key: str = ""
    redis_url: str = ""
    redis_ttl_seconds: int = 86400
    audit_enabled: bool = True
    audit_backend: str = "sqlite"
    postgres_url: str = ""
    claim_user_id: str = "sub"
    claim_session_id: str = "session_id"
    claim_device_id: str = "device_id"
    platform_toolset: str = "app_gateway"
    cors_origins: list[str] = field(default_factory=list)
    # Phase 2
    vector_memory_enabled: bool = True
    vector_memory_top_k: int = 5
    vector_memory_backend: str = "auto"
    rate_limit_rpm: int = 60
    proxy_to_api_server: bool = False
    api_server_url: str = "http://127.0.0.1:8642"
    api_server_key: str = ""
    # Single-process: 100+ simultaneous LLM/agent runs (scale out with more instances)
    max_concurrent_agents: int = 128
    agent_executor_workers: int = 160
    agent_queue_timeout_seconds: float = 300.0
    per_user_skills_isolated: bool = True
    include_global_skills: bool = True
    enable_shared_skills: bool = False
    shared_skills_dir: str = ""
    per_user_api_keys: bool = True
    fallback_global_credentials: bool = False
    # Phone registration (app → SMS → JWT → onboarding → chat)
    auth_mode: str = "dev"
    dev_sms_code: str = "111111"
    sms: Dict[str, Any] = field(default_factory=dict)
    sms_sign_name: str = ""
    sms_template_code: str = ""
    sms_template_param: str = "code"
    sms_region: str = ""
    sms_sdk_app_id: str = ""
    sms_template_id: str = ""
    sms_from_number: str = ""
    sms_webhook_url: str = ""
    sms_message_template: str = "Your verification code is {code}"
    sms_otp_ttl_seconds: int = 300
    jwt_ttl_hours: int = 720
    refresh_tokens_enabled: bool = True
    jwt_access_ttl_minutes: int = 120
    jwt_refresh_ttl_days: int = 30
    require_onboarding_before_chat: bool = True
    onboarding_models: list = field(default_factory=list)
    user_registry_backend: str = "auto"
    postgres_only: bool = False
    require_redis: bool = False
    trusted_proxy_ips: list[str] = field(default_factory=list)
    metrics_enabled: bool = True
    # Production / abuse / compliance
    expose_dev_code: bool = False
    daily_chat_limit: int = 0
    daily_token_limit: int = 0
    max_concurrent_chats_per_user: int = 2
    agent_max_iterations: int = 25
    sse_heartbeat_seconds: float = 20.0
    sse_stream_timeout_seconds: float = 600.0
    workspace_backend: str = "local"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "hermes-workspaces"
    minio_secure: bool = False
    minio_prefix: str = "workspaces"
    workspace_minio_async_upload: bool = True
    workspace_upload_workers: int = 8
    workspace_search_prefetch_max_files: int = 100
    workspace_cache_gc_enabled: bool = True
    workspace_cache_ttl_hours: float = 72.0
    workspace_cache_max_mb: float = 256.0
    workspace_cache_gc_interval_seconds: int = 300
    auth_sms_per_ip_per_hour: int = 30
    auth_sms_per_phone_per_day: int = 10
    auth_login_failures_per_phone: int = 15
    sms_captcha_enabled: bool = True
    sms_captcha_ttl_seconds: int = 300
    sms_captcha_max_operand: int = 20  # legacy; slider captcha ignores this
    sms_captcha_tolerance_bp: int = 35
    data_retention_days: int = 365
    data_retention_interval_hours: int = 24
    workspace_upload_max_retries: int = 3
    web_cookie_auth: bool = True
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str = ""
    delete_account_sms_verify: bool = True
    # When False (default), chat turns persist via incremental Postgres append only.
    session_json_snapshot: bool = False


_OPERATOR_SECRET_KEYS = ("jwt_secret", "app_key")


def _parse_str_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _load_operator_config_sections() -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Operator ``~/.hermes/config.yaml`` — not per-user ``HERMES_HOME`` trees."""
    try:
        from hermes_constants import get_default_hermes_root

        path = get_default_hermes_root() / "config.yaml"
        if not path.is_file():
            return {}, {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return {}, {}
        app_gateway = raw.get("app_gateway") or {}
        storage = raw.get("storage") or {}
        return (
            app_gateway if isinstance(app_gateway, dict) else {},
            storage if isinstance(storage, dict) else {},
        )
    except Exception:
        return {}, {}


def _load_operator_app_gateway_section() -> Dict[str, Any]:
    app_gateway, _ = _load_operator_config_sections()
    return app_gateway


def load_app_gateway_config() -> AppGatewayConfig:
    cfg: Dict[str, Any] = {}
    storage: Dict[str, Any] = {}
    try:
        from hermes_cli.config import load_config

        raw = load_config() or {}
        cfg = raw.get("app_gateway") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        storage = raw.get("storage") or {}
        if not isinstance(storage, dict):
            storage = {}
    except Exception:
        pass

    operator_cfg, operator_storage = _load_operator_config_sections()
    # Per-user ``load_config()`` (ContextVar override or ``HERMES_HOME`` env pointing
    # at ``app_gateway/users/<id>/``) merges DEFAULT_CONFIG and lacks operator
    # infrastructure keys. Operator settings always win on conflict.
    cfg = {**cfg, **operator_cfg}
    storage = {**storage, **operator_storage}
    for key in _OPERATOR_SECRET_KEYS:
        if not str(cfg.get(key) or "").strip():
            val = str(operator_cfg.get(key) or "").strip()
            if val:
                cfg[key] = val

    operator_storage_pg = str((operator_storage or {}).get("postgres_url") or "").strip()
    storage_pg = str((storage or {}).get("postgres_url") or "").strip()
    postgres_url = (
        os.environ.get("APP_GATEWAY_POSTGRES_URL", "").strip()
        or os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
        or str(cfg.get("postgres_url") or "").strip()
        or storage_pg
        or str(operator_cfg.get("postgres_url") or "").strip()
        or operator_storage_pg
    )
    jwt_secret = (
        os.environ.get("APP_GATEWAY_JWT_SECRET", "").strip()
        or str(cfg.get("jwt_secret") or "").strip()
    )
    app_key = (
        os.environ.get("APP_GATEWAY_APP_KEY", "").strip()
        or str(cfg.get("app_key") or "").strip()
    )
    redis_url = (
        os.environ.get("APP_GATEWAY_REDIS_URL", "").strip()
        or str(cfg.get("redis_url") or "").strip()
    )
    api_server_key = (
        os.environ.get("API_SERVER_KEY", "").strip()
        or str(cfg.get("api_server_key") or "").strip()
    )
    api_server_url = (
        os.environ.get("APP_GATEWAY_API_SERVER_URL", "").strip()
        or str(cfg.get("api_server_url") or "http://127.0.0.1:8642").strip()
    )

    cors = cfg.get("cors_origins") or []
    if isinstance(cors, str):
        cors = [c.strip() for c in cors.split(",") if c.strip()]

    return AppGatewayConfig(
        enabled=bool(cfg.get("enabled", False)),
        host=str(cfg.get("host") or "127.0.0.1"),
        port=int(cfg.get("port") or 8787),
        jwt_secret=jwt_secret,
        jwt_algorithm=str(cfg.get("jwt_algorithm") or "HS256"),
        require_jwt=bool(cfg.get("require_jwt", True)),
        app_key=app_key,
        redis_url=redis_url,
        redis_ttl_seconds=int(cfg.get("redis_ttl_seconds") or 86400),
        audit_enabled=bool(cfg.get("audit_enabled", True)),
        audit_backend=str(cfg.get("audit_backend") or "sqlite"),
        postgres_url=postgres_url,
        claim_user_id=str(cfg.get("claim_user_id") or "sub"),
        claim_session_id=str(cfg.get("claim_session_id") or "session_id"),
        claim_device_id=str(cfg.get("claim_device_id") or "device_id"),
        platform_toolset=str(cfg.get("platform_toolset") or "app_gateway"),
        cors_origins=list(cors),
        vector_memory_enabled=bool(cfg.get("vector_memory_enabled", True)),
        vector_memory_top_k=int(cfg.get("vector_memory_top_k") or 5),
        vector_memory_backend=str(cfg.get("vector_memory_backend") or "auto"),
        rate_limit_rpm=int(cfg.get("rate_limit_rpm") or 60),
        proxy_to_api_server=bool(cfg.get("proxy_to_api_server", False)),
        api_server_url=api_server_url,
        api_server_key=api_server_key,
        max_concurrent_agents=int(cfg.get("max_concurrent_agents") or 128),
        agent_executor_workers=int(cfg.get("agent_executor_workers") or 160),
        agent_queue_timeout_seconds=float(cfg.get("agent_queue_timeout_seconds") or 300.0),
        per_user_skills_isolated=bool(cfg.get("per_user_skills_isolated", True)),
        include_global_skills=bool(cfg.get("include_global_skills", True)),
        enable_shared_skills=bool(cfg.get("enable_shared_skills", False)),
        shared_skills_dir=str(cfg.get("shared_skills_dir") or "").strip(),
        per_user_api_keys=bool(cfg.get("per_user_api_keys", True)),
        fallback_global_credentials=bool(cfg.get("fallback_global_credentials", False)),
        auth_mode=str(cfg.get("auth_mode") or "dev"),
        dev_sms_code=str(cfg.get("dev_sms_code") or "111111"),
        sms=dict(cfg.get("sms") or {}) if isinstance(cfg.get("sms"), dict) else {},
        sms_sign_name=str(cfg.get("sms_sign_name") or "").strip(),
        sms_template_code=str(cfg.get("sms_template_code") or "").strip(),
        sms_template_param=str(cfg.get("sms_template_param") or "code").strip() or "code",
        sms_region=str(cfg.get("sms_region") or "").strip(),
        sms_sdk_app_id=str(cfg.get("sms_sdk_app_id") or "").strip(),
        sms_template_id=str(cfg.get("sms_template_id") or "").strip(),
        sms_from_number=str(cfg.get("sms_from_number") or "").strip(),
        sms_webhook_url=str(cfg.get("sms_webhook_url") or "").strip(),
        sms_message_template=str(
            cfg.get("sms_message_template") or "Your verification code is {code}"
        ),
        sms_otp_ttl_seconds=int(cfg.get("sms_otp_ttl_seconds") or 300),
        jwt_ttl_hours=int(cfg.get("jwt_ttl_hours") or 720),
        refresh_tokens_enabled=bool(cfg.get("refresh_tokens_enabled", True)),
        jwt_access_ttl_minutes=int(cfg.get("jwt_access_ttl_minutes") or 120),
        jwt_refresh_ttl_days=int(cfg.get("jwt_refresh_ttl_days") or 30),
        require_onboarding_before_chat=bool(cfg.get("require_onboarding_before_chat", True)),
        onboarding_models=list(cfg.get("onboarding_models") or []),
        user_registry_backend=str(cfg.get("user_registry_backend") or "auto"),
        postgres_only=bool(cfg.get("postgres_only") or storage.get("postgres_only")),
        require_redis=bool(cfg.get("require_redis", False)),
        trusted_proxy_ips=_parse_str_list(cfg.get("trusted_proxy_ips")),
        metrics_enabled=bool(cfg.get("metrics_enabled", True)),
        expose_dev_code=bool(cfg.get("expose_dev_code", False)),
        daily_chat_limit=int(cfg.get("daily_chat_limit") or 0),
        daily_token_limit=int(cfg.get("daily_token_limit") or 0),
        max_concurrent_chats_per_user=int(cfg.get("max_concurrent_chats_per_user") or 2),
        agent_max_iterations=int(cfg.get("agent_max_iterations") or 25),
        sse_heartbeat_seconds=float(cfg.get("sse_heartbeat_seconds") or 20),
        sse_stream_timeout_seconds=float(cfg.get("sse_stream_timeout_seconds") or 600),
        workspace_backend=str(cfg.get("workspace_backend") or "local").strip().lower(),
        minio_endpoint=str(
            os.environ.get("APP_GATEWAY_MINIO_ENDPOINT", "").strip()
            or cfg.get("minio_endpoint")
            or "127.0.0.1:9000"
        ).strip(),
        minio_access_key=str(
            os.environ.get("APP_GATEWAY_MINIO_ACCESS_KEY", "").strip()
            or cfg.get("minio_access_key")
            or "minioadmin"
        ).strip(),
        minio_secret_key=str(
            os.environ.get("APP_GATEWAY_MINIO_SECRET_KEY", "").strip()
            or cfg.get("minio_secret_key")
            or "minioadmin"
        ).strip(),
        minio_bucket=str(cfg.get("minio_bucket") or "hermes-workspaces").strip(),
        minio_secure=bool(cfg.get("minio_secure", False)),
        minio_prefix=str(cfg.get("minio_prefix") or "workspaces").strip().strip("/"),
        workspace_minio_async_upload=bool(cfg.get("workspace_minio_async_upload", True)),
        workspace_upload_workers=int(cfg.get("workspace_upload_workers") or 8),
        workspace_search_prefetch_max_files=int(cfg.get("workspace_search_prefetch_max_files") or 100),
        workspace_cache_gc_enabled=bool(cfg.get("workspace_cache_gc_enabled", True)),
        workspace_cache_ttl_hours=float(cfg.get("workspace_cache_ttl_hours") or 72),
        workspace_cache_max_mb=float(cfg.get("workspace_cache_max_mb") or 256),
        workspace_cache_gc_interval_seconds=int(cfg.get("workspace_cache_gc_interval_seconds") or 300),
        auth_sms_per_ip_per_hour=int(cfg.get("auth_sms_per_ip_per_hour") or 30),
        auth_sms_per_phone_per_day=int(cfg.get("auth_sms_per_phone_per_day") or 10),
        auth_login_failures_per_phone=int(cfg.get("auth_login_failures_per_phone") or 15),
        sms_captcha_enabled=bool(cfg.get("sms_captcha_enabled", True)),
        sms_captcha_ttl_seconds=int(cfg.get("sms_captcha_ttl_seconds") or 300),
        sms_captcha_max_operand=int(cfg.get("sms_captcha_max_operand") or 20),
        sms_captcha_tolerance_bp=int(cfg.get("sms_captcha_tolerance_bp") or 35),
        data_retention_days=int(cfg.get("data_retention_days") or 365),
        data_retention_interval_hours=int(cfg.get("data_retention_interval_hours") or 24),
        workspace_upload_max_retries=int(cfg.get("workspace_upload_max_retries") or 3),
        web_cookie_auth=bool(cfg.get("web_cookie_auth", True)),
        cookie_secure=bool(cfg.get("cookie_secure", False)),
        cookie_samesite=str(cfg.get("cookie_samesite") or "lax"),
        cookie_domain=str(cfg.get("cookie_domain") or "").strip(),
        delete_account_sms_verify=bool(cfg.get("delete_account_sms_verify", True)),
        session_json_snapshot=bool(cfg.get("session_json_snapshot", False)),
    )
