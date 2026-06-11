"""HttpOnly cookie helpers for web clients (XSS-resistant token storage)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from plugins.app_gateway.config import AppGatewayConfig

ACCESS_COOKIE = "hermes_access"
REFRESH_COOKIE = "hermes_refresh"
COOKIE_AUTH_HEADER = "x-hermes-cookie-auth"

_current_request: ContextVar[Any] = ContextVar("hermes_app_gateway_request", default=None)


def bind_request(request: Any) -> Any:
    return _current_request.set(request)


def reset_request(token: Any) -> None:
    _current_request.reset(token)


def current_request() -> Any:
    return _current_request.get()


def web_cookie_auth_enabled(config: AppGatewayConfig) -> bool:
    return bool(getattr(config, "web_cookie_auth", True))


def client_wants_cookie_auth(request: Any) -> bool:
    if request is None:
        return False
    header = (getattr(request, "headers", None) or {}).get(COOKIE_AUTH_HEADER)
    return str(header or "").strip().lower() in {"1", "true", "yes"}


def _cookie_params(config: AppGatewayConfig) -> dict[str, Any]:
    samesite = str(getattr(config, "cookie_samesite", "lax") or "lax").strip().lower()
    if samesite not in {"lax", "strict", "none"}:
        samesite = "lax"
    return {
        "httponly": True,
        "secure": bool(getattr(config, "cookie_secure", False)),
        "samesite": samesite,
    }


def set_auth_cookies(
    response: Any,
    config: AppGatewayConfig,
    *,
    access_token: str,
    refresh_token: Optional[str],
    access_max_age: int,
    refresh_max_age: Optional[int],
) -> None:
    if not web_cookie_auth_enabled(config):
        return
    params = _cookie_params(config)
    domain = str(getattr(config, "cookie_domain", "") or "").strip() or None
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=max(60, int(access_max_age)),
        path="/",
        domain=domain,
        **params,
    )
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE,
            refresh_token,
            max_age=max(3600, int(refresh_max_age or access_max_age)),
            path="/v1/auth",
            domain=domain,
            **params,
        )


def clear_auth_cookies(response: Any, config: AppGatewayConfig) -> None:
    if not web_cookie_auth_enabled(config):
        return
    domain = str(getattr(config, "cookie_domain", "") or "").strip() or None
    params = {"path": "/", "domain": domain}
    response.delete_cookie(ACCESS_COOKIE, **params)
    response.delete_cookie(REFRESH_COOKIE, path="/v1/auth", domain=domain)


def access_token_from_request(
    request: Any = None,
    *,
    authorization: Optional[str] = None,
    x_user_token: Optional[str] = None,
) -> str:
    from plugins.app_gateway.auth import parse_bearer_token

    token = (x_user_token or "").strip() or parse_bearer_token(authorization) or ""
    if token:
        return token
    req = request if request is not None else current_request()
    if req is None:
        return ""
    cookies = getattr(req, "cookies", None)
    if cookies is None:
        return ""
    return str(cookies.get(ACCESS_COOKIE) or "").strip()


def refresh_token_from_request(
    request: Any = None,
    body_token: Optional[str] = None,
) -> str:
    token = str(body_token or "").strip()
    if token:
        return token
    req = request if request is not None else current_request()
    if req is None:
        return ""
    cookies = getattr(req, "cookies", None)
    if cookies is None:
        return ""
    return str(cookies.get(REFRESH_COOKIE) or "").strip()
