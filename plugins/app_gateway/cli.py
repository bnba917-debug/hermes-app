"""CLI: ``hermes app-gateway start|token|status|init``."""

from __future__ import annotations

import argparse
import sys
import time

from hermes_constants import display_hermes_home

from plugins.app_gateway.auth import encode_hs256_jwt
from plugins.app_gateway.config import load_app_gateway_config
from plugins.app_gateway.config_registry import ConfigRegistry


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="app_gateway_action")

    start_p = subs.add_parser("start", help="Start the App Gateway HTTP server")
    start_p.add_argument("--host", default="")
    start_p.add_argument("--port", type=int, default=0)

    token_p = subs.add_parser("token", help="Print a dev JWT for testing")
    token_p.add_argument("--user-id", default="user-demo")
    token_p.add_argument("--session-id", default="session-1")
    token_p.add_argument("--device-id", default="")
    token_p.add_argument("--ttl", type=int, default=3600, help="Token lifetime seconds")

    subs.add_parser("init", help="Create app_gateway overrides.yaml template")
    subs.add_parser("status", help="Show app gateway configuration")


def app_gateway_command(args) -> None:
    action = getattr(args, "app_gateway_action", None) or "status"
    if action == "start":
        _cmd_start(args)
    elif action == "token":
        _cmd_token(args)
    elif action == "init":
        _cmd_init(args)
    else:
        _cmd_status(args)


def _cmd_status(args) -> None:
    cfg = load_app_gateway_config()
    home = display_hermes_home()
    reg = ConfigRegistry()
    print("Hermes App Gateway (phase 2)")
    print(f"  config home:       {home}")
    print(f"  enabled:           {cfg.enabled}")
    print(f"  listen:            {cfg.host}:{cfg.port}")
    print(f"  require_jwt:       {cfg.require_jwt}")
    print(f"  jwt_secret set:    {bool(cfg.jwt_secret)}")
    print(f"  app_key set:       {bool(cfg.app_key)}")
    print(f"  redis:             {cfg.redis_url or '(disabled)'}")
    print(f"  audit_backend:     {cfg.audit_backend}")
    print(f"  postgres_url set:  {bool(cfg.postgres_url)}")
    print(f"  user_registry:     {cfg.user_registry_backend}")
    try:
        from plugins.app_gateway.user_registry_factory import resolve_user_registry_backend

        resolved, _ = resolve_user_registry_backend()
        print(f"  user_registry resolved: {resolved}")
    except Exception:
        pass
    print(f"  vector_memory:     {cfg.vector_memory_enabled} (top_k={cfg.vector_memory_top_k})")
    print(f"  rate_limit_rpm:    {cfg.rate_limit_rpm}")
    print(f"  proxy_api_server:  {cfg.proxy_to_api_server} → {cfg.api_server_url}")
    print(f"  overrides:         {reg.path} ({'exists' if reg.path.is_file() else 'missing'})")
    print()
    print("Endpoints:")
    print(f"  POST http://{cfg.host}:{cfg.port}/v1/chat/completions")
    print(f"  POST http://{cfg.host}:{cfg.port}/v1/feedback")
    print(f"  GET  http://{cfg.host}:{cfg.port}/v1/memory/search?q=...")
    print(f"  POST http://{cfg.host}:{cfg.port}/v1/admin/config/reload")


def _cmd_init(args) -> None:
    path = ConfigRegistry().scaffold_if_missing()
    print(f"Created template: {path}")
    print("Edit system_prompt_prefix / tools_note, then:")
    print("  hermes app-gateway start")
    print("  curl -X POST -H X-App-Key: ... http://127.0.0.1:8787/v1/admin/config/reload")


def _cmd_token(args) -> None:
    cfg = load_app_gateway_config()
    if not cfg.jwt_secret:
        print(
            "Set APP_GATEWAY_JWT_SECRET or app_gateway.jwt_secret in config.yaml",
            file=sys.stderr,
        )
        sys.exit(1)
    now = int(time.time())
    payload = {
        "sub": args.user_id,
        "session_id": args.session_id,
        "iat": now,
        "exp": now + int(args.ttl),
    }
    if args.device_id:
        payload["device_id"] = args.device_id
    token = encode_hs256_jwt(payload, cfg.jwt_secret)
    print(token)


def _sanitize_gateway_process_env() -> None:
    """Drop a polluted ``HERMES_HOME`` that points at a per-user tree."""
    import os
    from pathlib import Path

    from plugins.app_gateway.user_scope import _lift_operator_root

    raw = os.environ.get("HERMES_HOME", "").strip()
    if not raw:
        return
    lifted = _lift_operator_root(Path(raw))
    if lifted.resolve() != Path(raw).resolve():
        os.environ.pop("HERMES_HOME", None)


def _cmd_start(args) -> None:
    _sanitize_gateway_process_env()
    cfg = load_app_gateway_config()
    host = args.host or cfg.host
    port = args.port or cfg.port
    if cfg.require_jwt and not cfg.jwt_secret:
        print(
            "Warning: require_jwt is true but no jwt_secret — set APP_GATEWAY_JWT_SECRET",
            file=sys.stderr,
        )
    try:
        import uvicorn
    except ImportError:
        print("Install web extra: uv pip install -e '.[web]'", file=sys.stderr)
        sys.exit(1)

    from plugins.app_gateway.server import create_app

    app = create_app(cfg)
    print(f"Starting Hermes App Gateway v0.2 on http://{host}:{port}")
    if cfg.proxy_to_api_server:
        print(f"  Proxy mode: forwarding to {cfg.api_server_url}")
    uvicorn.run(app, host=host, port=port, log_level="info")
