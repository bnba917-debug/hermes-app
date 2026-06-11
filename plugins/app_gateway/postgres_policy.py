"""PG-only mode — refuse SQLite fallbacks for App Gateway storage."""

from __future__ import annotations

from typing import Optional, Tuple


class PostgresOnlyError(RuntimeError):
    """Raised when ``postgres_only`` is enabled but SQLite would be used."""


def load_postgres_only_flag() -> bool:
    """True when operator ``config.yaml`` enables PG-only under storage or app_gateway."""
    try:
        from agent.session_storage.config import _load_storage_config

        storage, app_gateway = _load_storage_config()
        if bool((app_gateway or {}).get("postgres_only")):
            return True
        if bool((storage or {}).get("postgres_only")):
            return True
    except Exception:
        pass
    return False


def require_postgres_dsn(dsn: Optional[str], *, component: str) -> str:
    url = str(dsn or "").strip()
    if load_postgres_only_flag() and not url:
        raise PostgresOnlyError(
            f"{component}: postgres_only=true requires postgres_url to be configured"
        )
    return url


def reject_sqlite_backend(
    backend: str,
    *,
    component: str,
    dsn: Optional[str] = None,
) -> None:
    if not load_postgres_only_flag():
        return
    name = str(backend or "").strip().lower()
    if name != "postgres":
        raise PostgresOnlyError(
            f"{component}: postgres_only=true requires PostgreSQL backend, got {backend!r}"
        )
    require_postgres_dsn(dsn, component=component)


def normalize_audit_backend_name(backend: str) -> str:
    name = str(backend or "auto").strip().lower()
    if not load_postgres_only_flag():
        return name
    if name in {"sqlite", "dual", "both"}:
        raise PostgresOnlyError(
            f"audit: postgres_only=true forbids audit_backend={backend!r}"
        )
    return "postgres" if name in {"", "auto"} else name


def resolve_storage_backend_pg_only(
    backend: str,
    dsn: Optional[str],
    *,
    component: str,
) -> Tuple[str, Optional[str]]:
    """Apply PG-only policy after normal auto/sqlite/postgres resolution."""
    reject_sqlite_backend(backend, component=component, dsn=dsn)
    return backend, dsn


def validate_app_gateway_postgres_only(config: object) -> None:
    """Fail fast at gateway startup when PG-only is misconfigured."""
    if not getattr(config, "postgres_only", False) and not load_postgres_only_flag():
        return

    dsn = require_postgres_dsn(getattr(config, "postgres_url", ""), component="app_gateway")

    from agent.session_storage.config import (
        resolve_cron_backend,
        resolve_kanban_backend,
        resolve_session_backend,
    )
    from plugins.app_gateway.audit_backends import create_audit_backend
    from plugins.app_gateway.user_registry_factory import resolve_user_registry_backend
    from plugins.app_gateway.vector_memory import create_user_vector_memory

    for label, backend, url in (
        ("session", *resolve_session_backend()),
        ("kanban", *resolve_kanban_backend()),
        ("cron", *resolve_cron_backend()),
        ("user_registry", *resolve_user_registry_backend()),
    ):
        reject_sqlite_backend(backend, component=label, dsn=url)

    audit_name = normalize_audit_backend_name(getattr(config, "audit_backend", "auto"))
    create_audit_backend(
        audit_name,
        enabled=bool(getattr(config, "audit_enabled", True)),
        postgres_url=dsn,
        postgres_only=True,
    )
    create_user_vector_memory(config)
    from plugins.app_gateway.skill_registry import SkillRegistry

    SkillRegistry(dsn)
