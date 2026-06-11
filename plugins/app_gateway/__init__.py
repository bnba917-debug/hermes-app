"""Hermes App Gateway — multi-user HTTP surface (see tgs.html)."""

from plugins.app_gateway.cli import app_gateway_command, register_cli


def register(ctx) -> None:
    ctx.register_cli_command(
        name="app-gateway",
        help="Multi-user App SDK gateway (JWT, SSE, memory isolation)",
        setup_fn=register_cli,
        handler_fn=app_gateway_command,
        description=(
            "HTTP gateway for mobile/web clients: JWT identity injection, "
            "per-user session isolation, SSE streaming, optional Redis cache, "
            "and audit logging."
        ),
    )
