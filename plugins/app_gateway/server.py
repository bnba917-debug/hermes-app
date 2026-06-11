"""FastAPI App Gateway — JWT + SSE + phase-2 storage (tgs.html)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from starlette.requests import Request

from plugins.app_gateway.async_io import run_blocking

from plugins.app_gateway.api_proxy import ApiServerProxy
from plugins.app_gateway.audit import AuditStore
from plugins.app_gateway.auth import (
    JwtError,
    UserContext,
    extract_user_context,
    parse_bearer_token,
    verify_hs256_jwt,
)
from plugins.app_gateway.config import AppGatewayConfig
from plugins.app_gateway.config_registry import ConfigRegistry
from plugins.app_gateway.rate_limit import UserRateLimiter
from plugins.app_gateway.redis_store import SessionHotCache
from plugins.app_gateway.runtime import AppAgentRuntime
from plugins.app_gateway.session_keys import build_hermes_session_id
from plugins.app_gateway.vector_memory import create_user_vector_memory

logger = logging.getLogger(__name__)


def _warn_insecure_production_config(config: AppGatewayConfig) -> None:
    """Log warnings when production-unsafe settings are enabled."""
    if config.fallback_global_credentials:
        logger.warning(
            "app_gateway.fallback_global_credentials=true — tenants may use operator API keys"
        )
    if not config.require_jwt:
        logger.warning("app_gateway.require_jwt=false — unauthenticated chat is possible")
    if config.expose_dev_code:
        logger.warning("app_gateway.expose_dev_code=true — SMS codes leak in API responses")
    if config.enable_shared_skills:
        logger.warning(
            "app_gateway.enable_shared_skills=true — shared operator skills visible to tenants"
        )


def _client_ip(request: Request, trusted_proxies: Optional[List[str]] = None) -> str:
    direct = (request.client.host if request.client else "") or "unknown"
    proxies = {p.strip() for p in (trusted_proxies or []) if str(p).strip()}
    if proxies and direct in proxies:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return direct


def _session_storage_backend_label() -> str:
    try:
        from agent.session_storage.config import resolve_session_backend

        backend, _ = resolve_session_backend()
        return backend
    except Exception:
        return "sqlite"


def _user_registry_backend_label() -> str:
    try:
        from plugins.app_gateway.user_registry_factory import resolve_user_registry_backend

        backend, _ = resolve_user_registry_backend()
        return backend
    except Exception:
        return "sqlite"


async def _read_upload_bounded(upload, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            limit_mb = max(1, max_bytes // (1024 * 1024))
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {limit_mb}MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(config: AppGatewayConfig, *, vector_memory: Optional[Any] = None):
    try:
        from fastapi import FastAPI, Header, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, StreamingResponse
    except ImportError as exc:
        raise RuntimeError(
            "App gateway requires FastAPI. Install with: uv pip install -e '.[web]'"
        ) from exc

    app = FastAPI(title="Hermes App Gateway", version="0.4.0")

    @app.middleware("http")
    async def _request_context_middleware(request: Request, call_next):
        from plugins.app_gateway.auth_cookies import bind_request, reset_request

        req_token = bind_request(request)
        try:
            return await call_next(request)
        finally:
            reset_request(req_token)

    @app.on_event("startup")
    async def _startup_retention() -> None:
        from plugins.app_gateway.data_retention import maybe_run_data_retention

        await run_blocking(maybe_run_data_retention, config)

    if getattr(config, "metrics_enabled", True):
        from plugins.app_gateway import metrics as gw_metrics

        @app.middleware("http")
        async def _metrics_middleware(request: Request, call_next):
            route = gw_metrics.normalize_path(request.url.path)
            gw_metrics.counter_inc(
                "hermes_app_gateway_http_requests_total",
                labels={"method": request.method, "route": route},
            )
            response = await call_next(request)
            gw_metrics.counter_inc(
                "hermes_app_gateway_http_responses_total",
                labels={
                    "method": request.method,
                    "route": route,
                    "status": str(response.status_code),
                },
            )
            return response

    from plugins.app_gateway.postgres_policy import validate_app_gateway_postgres_only

    validate_app_gateway_postgres_only(config)

    cors_origins = list(config.cors_origins or [])
    if str(getattr(config, "auth_mode", "") or "").strip().lower() == "dev":
        _dev_web_origins = [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8081",
            "http://127.0.0.1:8081",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:50000",
            "http://127.0.0.1:50000",
            "http://localhost:53333",
            "http://127.0.0.1:53333",
        ]
        cors_origins = list(dict.fromkeys([*cors_origins, *_dev_web_origins]))
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    cache = SessionHotCache(config.redis_url, config.redis_ttl_seconds)
    from plugins.app_gateway.redis_policy import require_redis_for_production, validate_app_gateway_redis

    validate_app_gateway_redis(config, cache)
    _require_redis = require_redis_for_production(config)
    _trusted_proxies = list(getattr(config, "trusted_proxy_ips", None) or [])

    from plugins.app_gateway.user_scope import operator_app_gateway_root

    registry = ConfigRegistry(
        path=operator_app_gateway_root() / "overrides.yaml",
    )
    vector = (
        vector_memory
        if vector_memory is not None
        else create_user_vector_memory(config)
    )
    runtime = AppAgentRuntime(config, cache=cache, vector_memory=vector, config_registry=registry)
    audit = AuditStore(config)
    limiter = UserRateLimiter(
        config.rate_limit_rpm,
        redis_client=cache._client if cache.available else None,
        require_redis=_require_redis,
    )
    from plugins.app_gateway.auth_limits import AuthAbuseLimiter
    from plugins.app_gateway.quotas import QuotaExceeded, UserQuotaManager

    quotas = UserQuotaManager(
        config,
        redis_client=cache._client if cache.available else None,
        require_redis=_require_redis,
    )
    auth_guard = AuthAbuseLimiter(
        config,
        redis_client=cache._client if cache.available else None,
        require_redis=_require_redis,
    )
    from plugins.app_gateway.auth_tokens import AuthTokenService

    token_service = AuthTokenService(
        config,
        redis_client=cache._client if cache.available else None,
        require_redis=_require_redis,
    )
    _warn_insecure_production_config(config)
    proxy = ApiServerProxy(
        config.api_server_url if config.proxy_to_api_server else "",
        api_server_key=config.api_server_key,
    )

    def _check_app_key(x_app_key: Optional[str], authorization: Optional[str]) -> None:
        if not config.app_key:
            return
        candidate = (x_app_key or "").strip()
        if not candidate:
            candidate = parse_bearer_token(authorization) or ""
        if not candidate or candidate != config.app_key:
            raise HTTPException(status_code=401, detail="Invalid app key")

    def _check_app_key_for_user_route(
        x_app_key: Optional[str],
        authorization: Optional[str],
        x_user_token: Optional[str],
    ) -> None:
        """User JWT routes may authenticate via ``X-User-Token`` or HttpOnly cookie."""
        if (x_user_token or "").strip():
            return
        from plugins.app_gateway.auth_cookies import access_token_from_request

        if access_token_from_request(
            authorization=authorization,
            x_user_token=x_user_token,
        ):
            return
        _check_app_key(x_app_key, authorization)

    def _check_admin_key(x_app_key: Optional[str], authorization: Optional[str]) -> None:
        if not config.app_key:
            raise HTTPException(
                status_code=503,
                detail="app_gateway.app_key or APP_GATEWAY_APP_KEY is required for admin routes",
            )
        _check_app_key(x_app_key, authorization)

    def _resolve_user(
        authorization: Optional[str],
        x_user_token: Optional[str],
        *,
        x_hermes_session_id: Optional[str] = None,
    ) -> UserContext:
        from plugins.app_gateway.auth_cookies import access_token_from_request

        token = access_token_from_request(
            authorization=authorization,
            x_user_token=x_user_token,
        )
        if not token:
            if config.require_jwt:
                raise HTTPException(status_code=401, detail="JWT required")
            ctx = extract_user_context(
                {"sub": "dev", "session_id": "default"},
                claim_user_id=config.claim_user_id,
                claim_session_id=config.claim_session_id,
                claim_device_id=config.claim_device_id,
            )
        else:
            if not config.jwt_secret:
                raise HTTPException(
                    status_code=503,
                    detail="APP_GATEWAY_JWT_SECRET not configured",
                )
            try:
                claims = verify_hs256_jwt(token, config.jwt_secret)
            except JwtError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc

            token_type = str(claims.get("typ") or "").strip().lower()
            if token_type and token_type != "access":
                raise HTTPException(status_code=401, detail="access token required")

            try:
                ctx = extract_user_context(
                    claims,
                    claim_user_id=config.claim_user_id,
                    claim_session_id=config.claim_session_id,
                    claim_device_id=config.claim_device_id,
                )
            except JwtError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc

        sid_override = (x_hermes_session_id or "").strip()
        if sid_override:
            ctx = UserContext(
                user_id=ctx.user_id,
                session_id=sid_override,
                device_id=ctx.device_id,
                raw_claims=ctx.raw_claims,
            )
        return ctx

    def _auth_json_response(request: Request, payload: dict, pair: Any):
        """Return JSON; set HttpOnly auth cookies when the client requests cookie mode."""
        from plugins.app_gateway.auth_cookies import (
            client_wants_cookie_auth,
            set_auth_cookies,
            web_cookie_auth_enabled,
        )

        if not (
            web_cookie_auth_enabled(config)
            and client_wants_cookie_auth(request)
            and pair is not None
        ):
            return payload
        resp = JSONResponse(payload)
        set_auth_cookies(
            resp,
            config,
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            access_max_age=pair.expires_in,
            refresh_max_age=pair.refresh_expires_in,
        )
        return resp

    def _clear_auth_json_response(payload: dict | None = None):
        from plugins.app_gateway.auth_cookies import clear_auth_cookies

        resp = JSONResponse(payload or {"ok": True})
        clear_auth_cookies(resp, config)
        return resp

    async def _read_json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    @app.get("/health")
    async def health(deep: bool = False):
        data = {
            "status": "ok",
            "platform": "hermes-app-gateway",
            "version": "0.4.0",
            "redis": cache.available,
            "vector_memory": vector.enabled,
            "vector_memory_backend": getattr(
                config, "vector_memory_backend", "auto"
            ),
            "audit_backend": config.audit_backend,
            "jwt_configured": bool(config.jwt_secret),
            "jwt_secret_from_env": bool(
                __import__("os").environ.get("APP_GATEWAY_JWT_SECRET", "").strip()
            ),
            "postgres_configured": bool(config.postgres_url),
            "postgres_only": bool(getattr(config, "postgres_only", False)),
            "session_storage_backend": _session_storage_backend_label(),
            "proxy_to_api_server": config.proxy_to_api_server,
            "config_overrides": str(registry.path),
            "max_concurrent_agents": config.max_concurrent_agents,
            "per_user_skills_isolated": config.per_user_skills_isolated,
            "per_user_api_keys": config.per_user_api_keys,
            "fallback_global_credentials": config.fallback_global_credentials,
            "require_jwt": config.require_jwt,
            "enable_shared_skills": config.enable_shared_skills,
            "expose_dev_code": config.expose_dev_code,
            "user_registry_backend": _user_registry_backend_label(),
            "auth_limits_backend": auth_guard.backend,
            "refresh_tokens_enabled": token_service.refresh_enabled,
            "refresh_tokens_backend": token_service.refresh_backend,
            "rate_limit_backend": limiter.backend,
            "require_redis": _require_redis,
        }
        if _require_redis and not cache.available:
            data["status"] = "degraded"
        pool_stats = runtime._pool.stats()
        data["concurrency"] = {
            "active": pool_stats.active,
            "waiting": pool_stats.waiting,
            "max": pool_stats.max_concurrent,
            "total_started": pool_stats.total_started,
            "total_rejected": pool_stats.total_rejected,
        }
        if config.proxy_to_api_server:
            data["api_server_reachable"] = await proxy.health_check()
        try:
            from plugins.app_gateway.workspace_upload_queue import get_workspace_upload_queue

            data["workspace_upload_queue"] = get_workspace_upload_queue().stats()
        except Exception:
            data["workspace_upload_queue"] = {"pending": 0, "workers": 0}
        if deep:
            from plugins.app_gateway.health_checks import (
                probe_minio,
                probe_postgres,
                probe_redis,
                probe_upload_queue,
            )

            data["checks"] = {
                "postgres": await run_blocking(probe_postgres, config.postgres_url),
                "redis": await run_blocking(probe_redis, config.redis_url),
                "minio": await run_blocking(probe_minio),
                "upload_queue": await run_blocking(probe_upload_queue),
            }
            if not all(
                check.get("ok", False)
                for check in data["checks"].values()
                if check.get("configured", True)
            ):
                data["status"] = "degraded"
        return data

    @app.get("/metrics")
    async def prometheus_metrics():
        if not getattr(config, "metrics_enabled", True):
            raise HTTPException(status_code=404, detail="Metrics disabled")
        from fastapi.responses import PlainTextResponse

        from plugins.app_gateway import metrics as gw_metrics

        pool_stats = runtime._pool.stats()
        gw_metrics.gauge_set("hermes_app_gateway_agent_active", pool_stats.active)
        gw_metrics.gauge_set("hermes_app_gateway_agent_waiting", pool_stats.waiting)
        gw_metrics.gauge_set(
            "hermes_app_gateway_agent_max_concurrent",
            pool_stats.max_concurrent,
        )
        gw_metrics.gauge_set(
            "hermes_app_gateway_agent_total_rejected",
            pool_stats.total_rejected,
        )
        gw_metrics.gauge_set("hermes_app_gateway_redis_up", 1 if cache.available else 0)
        try:
            from plugins.app_gateway.workspace_upload_queue import get_workspace_upload_queue

            upload_stats = get_workspace_upload_queue().stats()
            gw_metrics.gauge_set(
                "hermes_app_gateway_upload_queue_pending",
                int(upload_stats.get("pending") or 0),
            )
            gw_metrics.gauge_set(
                "hermes_app_gateway_upload_queue_failed",
                int(upload_stats.get("failed") or 0),
            )
        except Exception:
            pass
        return PlainTextResponse(
            gw_metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.post("/v1/admin/config/reload")
    async def reload_config(
        x_app_key: Optional[str] = Header(None, alias="X-App-Key"),
        authorization: Optional[str] = Header(None),
    ):
        _check_admin_key(x_app_key, authorization)
        data = registry.reload(force=True)
        from gateway.runtime_cache import invalidate_gateway_agent_kit

        invalidate_gateway_agent_kit()
        return {"ok": True, "keys": list(data.keys())}

    def _ensure_chat_ready(ctx: UserContext) -> None:
        if not config.require_onboarding_before_chat:
            return
        from plugins.app_gateway.onboarding import onboarding_status

        st = onboarding_status(ctx)
        if st.get("ready_for_chat"):
            return
        raise HTTPException(
            status_code=403,
            detail={
                "code": "NEED_ONBOARDING",
                "message": "Complete onboarding (model + API key) before chatting.",
                "initialized": st.get("initialized"),
                "api_key_configured": (st.get("inference") or {}).get("api_key_configured"),
            },
        )

    @app.get("/v1/auth/sms/captcha")
    async def auth_sms_captcha():
        """Issue a slider CAPTCHA before SMS send (when ``sms_captcha_enabled``)."""
        from plugins.app_gateway.sms_captcha import (
            SmsCaptchaError,
            issue_sms_captcha,
            sms_captcha_enabled,
        )

        if not sms_captcha_enabled(config):
            return {"enabled": False}
        try:
            return issue_sms_captcha(config)
        except SmsCaptchaError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "CAPTCHA_UNAVAILABLE", "message": str(exc)},
            ) from exc

    @app.post("/v1/auth/sms/send")
    async def auth_sms_send(request: Request):
        """Send SMS OTP via configured provider (``auth_mode`` in config.yaml)."""
        from plugins.app_gateway.phone_auth import normalize_phone, send_sms_code
        from plugins.app_gateway.sms_captcha import SmsCaptchaError, sms_captcha_enabled, verify_sms_captcha
        from plugins.app_gateway.sms_provider import SmsDeliveryError

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            phone = normalize_phone(str(body.get("phone") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if sms_captcha_enabled(config):
            try:
                verify_sms_captcha(
                    config,
                    captcha_token=str(body.get("captcha_token") or ""),
                    captcha_answer=str(body.get("captcha_answer") or ""),
                )
            except SmsCaptchaError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "CAPTCHA_FAILED", "message": str(exc)},
                ) from exc
        try:
            auth_guard.check_sms_send(_client_ip(request, _trusted_proxies), phone)
        except ValueError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        try:
            return send_sms_code(config, phone)
        except SmsDeliveryError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "SMS_DELIVERY_FAILED", "message": str(exc)},
            ) from exc

    @app.post("/v1/auth/register")
    async def auth_register(request: Request):
        """Phone register — same as login (upsert user, return JWT)."""
        return await auth_login(request)

    @app.post("/v1/auth/login")
    async def auth_login(request: Request):
        """Phone + SMS code → ``access_token`` (use in ``Authorization: Bearer``)."""
        from plugins.app_gateway.phone_auth import normalize_phone, verify_phone_login

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            phone = normalize_phone(str(body.get("phone") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        code = str(body.get("code") or body.get("sms_code") or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="code is required")
        try:
            auth_guard.check_login_allowed(phone)
        except ValueError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        try:
            record, _, is_new = verify_phone_login(
                config,
                phone=phone,
                code=code,
                device_id=str(body.get("device_id") or "").strip() or None,
                session_id=str(body.get("session_id") or "app"),
            )
        except ValueError as exc:
            auth_guard.record_login_failure(phone)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        auth_guard.clear_login_failures(phone)
        from plugins.app_gateway.onboarding import onboarding_status
        from plugins.app_gateway.phone_auth import mask_phone

        session_id = str(body.get("session_id") or "app")
        device_id = str(body.get("device_id") or "").strip() or None
        pair = token_service.issue_login_tokens(
            user_id=record.user_id,
            phone=phone,
            session_id=session_id,
            device_id=device_id,
        )
        ctx = UserContext(
            user_id=record.user_id,
            session_id=session_id,
            device_id=device_id,
            raw_claims={"sub": record.user_id, "phone": phone},
        )
        st = onboarding_status(ctx)
        payload = {
            "access_token": pair.access_token,
            "token_type": "bearer",
            "expires_in": pair.expires_in,
            "user_id": record.user_id,
            "phone": mask_phone(phone),
            "is_new_user": is_new,
            "initialized": st.get("initialized"),
            "ready_for_chat": st.get("ready_for_chat"),
        }
        if pair.refresh_token:
            payload["refresh_token"] = pair.refresh_token
            payload["refresh_expires_in"] = pair.refresh_expires_in
        return _auth_json_response(request, payload, pair)

    @app.post("/v1/auth/refresh")
    async def auth_refresh(request: Request):
        """Exchange a refresh token for a new access + refresh token pair."""
        from plugins.app_gateway.auth_tokens import RefreshTokenError, RefreshTokenReuseError
        from plugins.app_gateway.auth_cookies import refresh_token_from_request

        body = await _read_json_body(request)
        refresh_token = refresh_token_from_request(body_token=body.get("refresh_token"))
        if not refresh_token:
            raise HTTPException(status_code=400, detail="refresh_token is required")
        try:
            pair = token_service.refresh_tokens(refresh_token)
        except RefreshTokenReuseError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RefreshTokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        payload = {
            "access_token": pair.access_token,
            "token_type": "bearer",
            "expires_in": pair.expires_in,
        }
        if pair.refresh_token:
            payload["refresh_token"] = pair.refresh_token
            payload["refresh_expires_in"] = pair.refresh_expires_in
        return _auth_json_response(request, payload, pair)

    @app.post("/v1/auth/logout")
    async def auth_logout(request: Request):
        """Revoke a refresh token (best-effort; access JWT remains valid until expiry)."""
        from plugins.app_gateway.auth_cookies import refresh_token_from_request

        body = await _read_json_body(request)
        refresh_token = refresh_token_from_request(body_token=body.get("refresh_token"))
        if refresh_token:
            token_service.revoke_refresh_token(refresh_token)
        return _clear_auth_json_response({"ok": True})

    @app.post("/v1/auth/logout/all")
    async def auth_logout_all(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Revoke all refresh tokens for the authenticated user."""
        ctx = _resolve_user(authorization, x_user_token)
        token_service.revoke_all_user_tokens(ctx.user_id)
        return _clear_auth_json_response({"ok": True, "user_id": ctx.user_id})

    @app.get("/v1/legal/{doc}")
    async def legal_doc(doc: str):
        from plugins.app_gateway.account_compliance import legal_document_path

        path = legal_document_path(doc)
        if path is None:
            raise HTTPException(status_code=404, detail="Legal document not found")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(
            path.read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
        )

    @app.get("/v1/me/usage")
    async def me_usage(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        ctx = _resolve_user(authorization, x_user_token)
        return {"user_id": ctx.user_id, **quotas.usage_snapshot(ctx.user_id)}

    @app.delete("/v1/me")
    async def delete_me(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Self-service account deletion — irreversible."""
        from plugins.app_gateway.account_compliance import (
            delete_user_account,
            verify_delete_account_code,
        )

        ctx = _resolve_user(authorization, x_user_token)
        body = await _read_json_body(request)
        if body.get("confirm") is not True:
            raise HTTPException(
                status_code=400,
                detail='Body must include {"confirm": true}',
            )
        code = str(body.get("code") or body.get("sms_code") or "").strip()
        try:
            verify_delete_account_code(ctx.user_id, code, config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        token_service.revoke_all_user_tokens(ctx.user_id)
        result = await run_blocking(
            delete_user_account,
            ctx,
            vector_memory=vector,
            audit=audit,
        )
        return _clear_auth_json_response(result)

    @app.post("/v1/me/delete/sms")
    async def delete_me_sms(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Send SMS OTP for account deletion confirmation."""
        from plugins.app_gateway.account_compliance import send_delete_account_sms

        ctx = _resolve_user(authorization, x_user_token)
        if not bool(getattr(config, "delete_account_sms_verify", True)):
            return {"ok": True, "skipped": True, "reason": "sms_verify_disabled"}
        try:
            auth_guard.check_sms_send(_client_ip(request, _trusted_proxies), ctx.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        try:
            return await run_blocking(send_delete_account_sms, ctx.user_id, config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/me/storage")
    async def me_storage(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.storage_snapshot import storage_usage_snapshot

        ctx = _resolve_user(authorization, x_user_token)
        snap = await run_blocking(storage_usage_snapshot, ctx.user_id)
        return {
            "user_id": ctx.user_id,
            **snap,
        }

    @app.get("/v1/onboarding/status")
    async def onboarding_status_route(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.onboarding import onboarding_status

        ctx = _resolve_user(authorization, x_user_token)
        return await run_blocking(onboarding_status, ctx)

    @app.get("/v1/onboarding/models")
    async def onboarding_models_route():
        from plugins.app_gateway.onboarding import list_onboarding_models

        return {
            "models": list_onboarding_models(
                config.onboarding_models or None,
            ),
        }

    @app.post("/v1/onboarding/complete")
    async def onboarding_complete(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """App save: model + API key → per-user home initialized, ready to chat."""
        from plugins.app_gateway.onboarding import complete_onboarding

        ctx = _resolve_user(authorization, x_user_token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            return await run_blocking(
                complete_onboarding,
                ctx,
                api_key=str(body.get("api_key") or ""),
                model=str(body.get("model") or ""),
                provider=str(body.get("provider") or "openrouter"),
                api_key_env=body.get("api_key_env"),
                base_url=body.get("base_url"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/me/inference")
    async def get_my_inference(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.user_credentials import user_credentials_status
        from plugins.app_gateway.user_scope import app_gateway_user_scope

        ctx = _resolve_user(authorization, x_user_token)

        def _load_status():
            with app_gateway_user_scope(ctx, include_global_skills=False):
                return user_credentials_status()

        status = await run_blocking(_load_status)
        return {"user_id": ctx.user_id, **status}

    @app.put("/v1/me/inference")
    async def put_my_inference(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.user_credentials import set_user_inference_config

        ctx = _resolve_user(authorization, x_user_token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            data = set_user_inference_config(
                ctx,
                api_key=body.get("api_key"),
                api_key_env=body.get("api_key_env"),
                provider=body.get("provider"),
                model=body.get("model"),
                base_url=body.get("base_url"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **data}

    @app.get("/v1/sessions")
    async def list_sessions_route(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
        x_hermes_session_id: Optional[str] = Header(None, alias="X-Hermes-Session-Id"),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        from plugins.app_gateway.sessions_service import list_user_sessions

        ctx = _resolve_user(authorization, x_user_token, x_hermes_session_id=x_hermes_session_id)
        sessions = list_user_sessions(ctx, limit=limit, offset=offset)
        return {
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "sessions": sessions,
        }

    @app.post("/v1/sessions")
    async def create_session_route(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.sessions_service import create_user_session

        ctx = _resolve_user(authorization, x_user_token)
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        if not isinstance(body, dict):
            body = {}
        try:
            data = create_user_session(
                ctx,
                session_id=str(body.get("session_id") or "").strip() or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **data}

    @app.patch("/v1/sessions/{logical_session_id}")
    async def patch_session_route(
        logical_session_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.sessions_service import set_user_session_title

        ctx = _resolve_user(authorization, x_user_token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            data = set_user_session_title(
                ctx,
                logical_session_id,
                str(body.get("title") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **data}

    @app.post("/v1/sessions/{logical_session_id}/title/suggest")
    async def suggest_session_title_route(
        logical_session_id: str,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.sessions_service import suggest_user_session_title

        ctx = _resolve_user(authorization, x_user_token)
        try:
            data = suggest_user_session_title(ctx, logical_session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **data}

    @app.get("/v1/sessions/{logical_session_id}/messages")
    async def session_messages_route(
        logical_session_id: str,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.sessions_service import get_user_messages

        ctx = _resolve_user(authorization, x_user_token)
        try:
            messages = get_user_messages(ctx, logical_session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "user_id": ctx.user_id,
            "session_id": logical_session_id,
            "messages": messages,
        }

    @app.post("/v1/chat/stop")
    async def chat_stop_route(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.run_registry import stop_run

        ctx = _resolve_user(authorization, x_user_token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        run_id = str(body.get("run_id") or body.get("completion_id") or "").strip()
        if not run_id:
            raise HTTPException(status_code=400, detail="run_id is required")
        if not stop_run(run_id, ctx.user_id):
            raise HTTPException(status_code=404, detail="Run not found or not stoppable")
        quotas.release_chat(ctx.user_id)
        return {"ok": True, "run_id": run_id}

    @app.post("/v1/runs/{run_id}/approval")
    async def run_approval_route(
        run_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.run_registry import resolve_approval
        from plugins.app_gateway.session_keys import build_gateway_session_key

        ctx = _resolve_user(authorization, x_user_token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        choice = str(body.get("choice") or body.get("decision") or "").strip().lower()
        if choice not in ("once", "session", "always", "deny"):
            raise HTTPException(status_code=400, detail="Invalid approval choice")
        key = build_gateway_session_key(ctx)
        if not resolve_approval(run_id, ctx.user_id, choice, gateway_session_key=key):
            raise HTTPException(status_code=404, detail="No pending approval for this run")
        return {"ok": True, "run_id": run_id, "choice": choice}

    @app.put("/v1/admin/users/{user_id}/inference")
    async def put_user_inference_admin(
        user_id: str,
        request: Request,
        x_app_key: Optional[str] = Header(None, alias="X-App-Key"),
        authorization: Optional[str] = Header(None),
    ):
        """Backend sets credentials for a user (requires ``app_key``)."""
        from plugins.app_gateway.user_credentials import set_user_inference_config

        _check_admin_key(x_app_key, authorization)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        ctx = UserContext(
            user_id=user_id,
            session_id=str(body.get("session_id") or "admin"),
            device_id=None,
            raw_claims={"sub": user_id},
        )
        try:
            data = set_user_inference_config(
                ctx,
                api_key=body.get("api_key"),
                api_key_env=body.get("api_key_env"),
                provider=body.get("provider"),
                model=body.get("model"),
                base_url=body.get("base_url"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user_id": user_id, **data}

    @app.get("/v1/skills")
    async def list_skills(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.skills_routes import list_user_skills

        ctx = _resolve_user(authorization, x_user_token)
        skills = list_user_skills(ctx, include_global=config.include_global_skills)
        return {"user_id": ctx.user_id, "skills": skills}

    @app.get("/v1/skills/config")
    async def skills_config(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.skills_service import get_skills_config

        ctx = _resolve_user(authorization, x_user_token)
        return get_skills_config(ctx)

    @app.put("/v1/skills/config")
    async def skills_config_update(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.skills_service import set_skills_disabled

        ctx = _resolve_user(authorization, x_user_token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        disabled = body.get("disabled")
        if disabled is None:
            raise HTTPException(status_code=400, detail="disabled array required")
        if not isinstance(disabled, list):
            raise HTTPException(status_code=400, detail="disabled must be a list")
        try:
            return set_skills_disabled(ctx, disabled)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/skills/{skill_name}")
    async def get_skill(
        skill_name: str,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.skills_service import get_user_skill

        ctx = _resolve_user(authorization, x_user_token)
        try:
            return get_user_skill(ctx, skill_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/skills/reload")
    async def reload_skills(
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        from plugins.app_gateway.skills_routes import reload_user_skills

        ctx = _resolve_user(authorization, x_user_token)
        return reload_user_skills(ctx)

    @app.post("/v1/audio/transcribe")
    async def audio_transcribe(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Upload audio → text (CLI STT stack)."""
        from plugins.app_gateway.voice_routes import transcribe_upload

        ctx = _resolve_user(authorization, x_user_token)
        _ensure_chat_ready(ctx)
        content_type = (request.headers.get("content-type") or "").lower()
        model = None
        file_bytes: bytes
        filename = "audio.wav"

        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                raise HTTPException(status_code=400, detail="file field required")
            file_bytes = await upload.read()
            filename = getattr(upload, "filename", None) or filename
            model = form.get("model")
            if model is not None:
                model = str(model)
        else:
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="JSON object or multipart required")
            import base64

            b64 = body.get("audio_base64") or body.get("data")
            if not b64:
                raise HTTPException(status_code=400, detail="audio_base64 required")
            file_bytes = base64.b64decode(str(b64), validate=False)
            filename = str(body.get("filename") or filename)
            model = body.get("model")

        if not file_bytes:
            raise HTTPException(status_code=400, detail="empty audio")
        try:
            result = await run_blocking(
                transcribe_upload,
                ctx,
                file_bytes=file_bytes,
                filename=filename,
                model=model,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **result}

    @app.post("/v1/audio/speech")
    async def audio_speech(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Text → speech file (CLI TTS stack). Returns JSON with ``file_path``."""
        from plugins.app_gateway.voice_routes import synthesize_speech

        ctx = _resolve_user(authorization, x_user_token)
        _ensure_chat_ready(ctx)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text required")
        try:
            result = await run_blocking(
                synthesize_speech,
                ctx,
                text=text,
                output_path=body.get("output_path"),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **result}

    @app.post("/v1/chat/attachments")
    async def chat_attachments_upload(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Upload a chat attachment into the user's workspace (``uploads/``)."""
        from plugins.app_gateway.chat_attachments import store_chat_attachment

        ctx = _resolve_user(authorization, x_user_token)
        _ensure_chat_ready(ctx)
        content_type = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" not in content_type:
            raise HTTPException(status_code=400, detail="multipart/form-data required")
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail="file field required")
        from plugins.app_gateway.chat_attachments import MAX_CHAT_ATTACHMENT_BYTES

        file_bytes = await _read_upload_bounded(upload, MAX_CHAT_ATTACHMENT_BYTES)
        filename = getattr(upload, "filename", None) or "upload"
        mime = getattr(upload, "content_type", None) or ""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: store_chat_attachment(
                    ctx,
                    file_bytes=file_bytes,
                    filename=str(filename),
                    mime_type=str(mime),
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user_id": ctx.user_id, **result}

    @app.get("/v1/workspace/download")
    async def workspace_download(
        path: str = Query(..., min_length=1),
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    ):
        """Download a file from the user's workspace sandbox (JWT required)."""
        from fastapi.responses import Response

        from plugins.app_gateway.workspace_files import read_workspace_file_for_user

        ctx = _resolve_user(authorization, x_user_token)
        loop = asyncio.get_running_loop()
        try:
            payload = await loop.run_in_executor(
                None,
                lambda: read_workspace_file_for_user(ctx.user_id, path),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="file not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=payload.data,
            media_type=payload.mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{payload.filename}"',
                "X-Hermes-Workspace-Path": payload.relative_path,
            },
        )

    @app.get("/v1/memory/search")
    async def memory_search(
        q: str = Query(..., min_length=1),
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
        x_hermes_session_id: Optional[str] = Header(None, alias="X-Hermes-Session-Id"),
    ):
        ctx = _resolve_user(
            None if x_user_token else authorization,
            x_user_token,
            x_hermes_session_id=x_hermes_session_id,
        )
        hits = await run_blocking(vector.search, ctx.user_id, q)
        return {"user_id": ctx.user_id, "query": q, "results": hits}

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
        x_hermes_session_id: Optional[str] = Header(None, alias="X-Hermes-Session-Id"),
    ):
        ctx = _resolve_user(
            None if x_user_token else authorization,
            x_user_token,
            x_hermes_session_id=x_hermes_session_id,
        )
        _ensure_chat_ready(ctx)
        if not limiter.allow(ctx.user_id):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        body = await request.json()
        messages = body.get("messages") or []
        stream = bool(body.get("stream", False))
        use_server_history = bool(body.get("use_server_history", False))

        from plugins.app_gateway.chat_messages import (
            openai_error_body,
            parse_chat_completions_messages,
        )

        parsed = parse_chat_completions_messages(messages)
        if parsed.error_message:
            raise HTTPException(
                status_code=400,
                detail=openai_error_body(
                    parsed.error_message,
                    code=parsed.error_code or "invalid_request_error",
                    param=parsed.error_param,
                ),
            )
        user_message = parsed.user_message
        history = parsed.history
        client_system = parsed.system_prompt

        quota_acquired = False
        try:
            quotas.check_and_acquire_chat(ctx.user_id)
            quota_acquired = True
        except QuotaExceeded as exc:
            headers = {}
            if exc.retry_after:
                headers["Retry-After"] = str(exc.retry_after)
            raise HTTPException(
                status_code=429,
                detail={"code": exc.code, "message": exc.message},
                headers=headers or None,
            ) from exc

        session_id = build_hermes_session_id(ctx)
        if use_server_history:
            server_hist = runtime.load_history(ctx, session_id)
            if server_hist:
                history = server_hist
        audit.log(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            device_id=ctx.device_id,
            event_type="chat.start",
            payload={
                "stream": stream,
                "hermes_session_id": session_id,
                "proxy": config.proxy_to_api_server,
            },
        )

        if config.proxy_to_api_server and proxy.enabled:
            try:
                if stream:
                    stream_gen = await proxy.chat_completions(ctx, body, stream=True)

                    async def forward():
                        async for chunk in stream_gen:
                            yield chunk

                    if quota_acquired:
                        quotas.release_chat(ctx.user_id)
                        quota_acquired = False
                    return StreamingResponse(forward(), media_type="text/event-stream")
                result = await proxy.chat_completions(ctx, body, stream=False)
                audit.log(
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    event_type="chat.done",
                    payload={"proxy": True},
                )
                if quota_acquired:
                    quotas.release_chat(ctx.user_id)
                    quota_acquired = False
                return result
            except Exception as exc:
                logger.warning("api_server proxy failed, falling back to in-process: %s", exc)

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        model_name = body.get("model") or "hermes-agent"
        created = int(time.time())

        from plugins.app_gateway.run_registry import pop_run, register_run
        from plugins.app_gateway.session_keys import build_gateway_session_key

        register_run(
            completion_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )
        gateway_session_key = build_gateway_session_key(ctx)

        if not stream:
            usage: Dict[str, Any] = {}
            try:
                result, usage = await runtime.run_chat(
                    ctx,
                    user_message,
                    conversation_history=history,
                    client_system_prompt=client_system,
                    run_id=completion_id,
                    gateway_session_key=gateway_session_key,
                )
            finally:
                pop_run(completion_id)
                if quota_acquired:
                    quotas.release_chat(ctx.user_id)
                    quota_acquired = False
            quotas.record_tokens(ctx.user_id, int(usage.get("total_tokens", 0) or 0))
            if result.get("error") == "queue_timeout":
                raise HTTPException(
                    status_code=503,
                    detail=result.get("final_response") or "Server busy",
                    headers={"Retry-After": "30"},
                )
            text = result.get("final_response") or result.get("error") or ""
            audit.log(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                event_type="chat.done",
                payload={"tokens": usage.get("total_tokens", 0)},
            )
            return {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "hermes_session_id": result.get("session_id", session_id),
                "hermes_user_id": ctx.user_id,
                "run_id": completion_id,
            }

        queue: asyncio.Queue = asyncio.Queue()
        agent_ref: list = [None]
        streamed_text: list = [False]

        def on_delta(delta):
            if delta is not None:
                streamed_text[0] = True
                queue.put_nowait(delta)

        def on_tool_start(_tool_call_id, name, args=None):
            queue.put_nowait(
                (
                    "__event__",
                    {
                        "object": "hermes.event",
                        "type": "tool.start",
                        "run_id": completion_id,
                        "name": name,
                    },
                )
            )

        def on_tool_complete(_tool_call_id, name, args=None, result_text=None):
            from plugins.app_gateway.workspace_files import extract_workspace_file_paths

            file_paths = extract_workspace_file_paths(name, args or {}, result_text)
            event: Dict[str, Any] = {
                "object": "hermes.event",
                "type": "tool.complete",
                "run_id": completion_id,
                "name": name,
            }
            if file_paths:
                event["files"] = [{"path": p} for p in file_paths]
            queue.put_nowait(("__event__", event))

        def on_event(event: Dict[str, Any]) -> None:
            queue.put_nowait(("__event__", event))

        async def run_agent_task():
            nonlocal quota_acquired
            usage_stream: Dict[str, Any] = {}
            try:
                result, usage_stream = await runtime.run_chat(
                    ctx,
                    user_message,
                    conversation_history=history,
                    client_system_prompt=client_system,
                    stream_delta_callback=on_delta,
                    tool_start_callback=on_tool_start,
                    tool_complete_callback=on_tool_complete,
                    agent_ref=agent_ref,
                    run_id=completion_id,
                    gateway_session_key=gateway_session_key,
                    event_callback=on_event,
                )
                if result.get("error") == "queue_timeout":
                    queue.put_nowait(("__error__", result.get("final_response") or "Server busy"))
                    return
                queue.put_nowait(("__done__", result))
            except Exception as exc:
                queue.put_nowait(("__error__", str(exc)))
            finally:
                pop_run(completion_id)
                quotas.record_tokens(
                    ctx.user_id, int(usage_stream.get("total_tokens", 0) or 0)
                )
                if quota_acquired:
                    quotas.release_chat(ctx.user_id)
                    quota_acquired = False
                queue.put_nowait(None)

        task = asyncio.create_task(run_agent_task())

        async def event_generator():
            nonlocal quota_acquired
            heartbeat = max(5.0, float(getattr(config, "sse_heartbeat_seconds", 20) or 20))
            stream_timeout = max(60.0, float(getattr(config, "sse_stream_timeout_seconds", 600) or 600))
            deadline = time.monotonic() + stream_timeout
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=min(heartbeat, remaining))
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        ping_evt = {
                            "object": "hermes.event",
                            "type": "heartbeat",
                            "run_id": completion_id,
                        }
                        yield f"data: {json.dumps(ping_evt, ensure_ascii=False)}\n\n"
                        continue
                    if item is None:
                        yield "data: [DONE]\n\n"
                        break
                    if isinstance(item, tuple) and item[0] == "__done__":
                        result = item[1]
                        final = (result.get("final_response") or "").strip()
                        if not final and result.get("error"):
                            final = str(result.get("error") or "").strip()
                        audit.log(
                            user_id=ctx.user_id,
                            session_id=ctx.session_id,
                            event_type="chat.done",
                            payload={"stream": True, "has_final": bool(final)},
                        )
                        sid = result.get("session_id", session_id)
                        # Non-streaming model responses: no deltas; send full text once.
                        if final and not streamed_text[0]:
                            chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model_name,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": final},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        done_evt = {
                            "object": "hermes.event",
                            "type": "chat.done",
                            "run_id": completion_id,
                            "hermes_session_id": sid,
                            "hermes_user_id": ctx.user_id,
                        }
                        if final:
                            done_evt["content"] = final
                        if result.get("error"):
                            done_evt["error"] = result.get("error")
                        yield f"data: {json.dumps(done_evt, ensure_ascii=False)}\n\n"
                        continue
                    if isinstance(item, tuple) and item[0] == "__event__":
                        yield f"data: {json.dumps(item[1], ensure_ascii=False)}\n\n"
                        continue
                    if isinstance(item, tuple) and item[0] == "__error__":
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_name,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": f"[error: {item[1]}]"},
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        break
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_name,
                        "choices": [
                            {"index": 0, "delta": {"content": item}, "finish_reason": None}
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    agent = agent_ref[0] if agent_ref else None
                    if agent is not None:
                        try:
                            agent.interrupt()
                        except Exception:
                            pass
                    task.cancel()
                if quota_acquired:
                    quotas.release_chat(ctx.user_id)
                    quota_acquired = False

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Hermes-User-Id": ctx.user_id,
                "X-Hermes-Session-Id": ctx.session_id,
                "X-Hermes-Run-Id": completion_id,
            },
        )

    @app.post("/v1/feedback")
    async def feedback(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
        x_hermes_session_id: Optional[str] = Header(None, alias="X-Hermes-Session-Id"),
    ):
        ctx = _resolve_user(
            None if x_user_token else authorization,
            x_user_token,
            x_hermes_session_id=x_hermes_session_id,
        )
        body = await request.json()
        rating = str(body.get("rating") or body.get("thumb") or "unknown")
        audit.log_feedback(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            rating=rating,
            comment=str(body.get("comment") or ""),
            message_id=str(body.get("message_id") or ""),
        )
        if body.get("store_memory") and vector.enabled:
            note = str(body.get("comment") or rating).strip()
            if note:
                vector.add(ctx.user_id, ctx.session_id, f"User feedback: {note}")
        return JSONResponse({"ok": True})

    return app
