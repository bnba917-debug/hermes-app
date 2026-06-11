"""Resolve Hermes storage backends (session, kanban, cron) from config."""

from __future__ import annotations

import os
from typing import Optional, Tuple


def _load_operator_config_sections() -> Tuple[dict, dict]:
    """Operator ``config.yaml`` sections — ignore per-user ``HERMES_HOME`` scope."""
    try:
        from hermes_constants import get_default_hermes_root
        import yaml

        path = get_default_hermes_root() / "config.yaml"
        if not path.is_file():
            return {}, {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return {}, {}
        storage = raw.get("storage") or {}
        app_gateway = raw.get("app_gateway") or {}
        return (
            storage if isinstance(storage, dict) else {},
            app_gateway if isinstance(app_gateway, dict) else {},
        )
    except Exception:
        return {}, {}


def _load_storage_config() -> Tuple[dict, dict]:
    storage: dict = {}
    app_gateway: dict = {}
    try:
        from hermes_cli.config import load_config

        raw = load_config() or {}
        storage = raw.get("storage") or {}
        if not isinstance(storage, dict):
            storage = {}
        app_gateway = raw.get("app_gateway") or {}
        if not isinstance(app_gateway, dict):
            app_gateway = {}
    except Exception:
        pass

    op_storage, op_ag = _load_operator_config_sections()
    if not str((storage or {}).get("postgres_url") or "").strip():
        storage = {**op_storage, **storage}
    if not str((app_gateway or {}).get("postgres_url") or "").strip():
        app_gateway = {**op_ag, **app_gateway}
    return storage, app_gateway


def resolve_postgres_url(
    storage: Optional[dict] = None,
    app_gateway: Optional[dict] = None,
) -> str:
    """Shared DSN for session store, app-gateway audit, and vector memory."""
    if storage is None or app_gateway is None:
        s, ag = _load_storage_config()
        storage = storage if storage is not None else s
        app_gateway = app_gateway if app_gateway is not None else ag

    storage_pg = str((storage or {}).get("postgres_url") or "").strip()
    return (
        os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
        or os.environ.get("APP_GATEWAY_POSTGRES_URL", "").strip()
        or str((app_gateway or {}).get("postgres_url") or "").strip()
        or storage_pg
    )


def resolve_session_backend(
    db_path=None,
) -> Tuple[str, Optional[str]]:
    """Return ``(backend, dsn)`` where backend is ``sqlite`` or ``postgres``.

    An explicit ``db_path`` (tests, custom locations) always forces SQLite.
    """
    if db_path is not None:
        return "sqlite", None

    storage, app_gateway = _load_storage_config()
    backend = str((storage or {}).get("session_backend") or "auto").strip().lower()
    if backend not in ("auto", "sqlite", "postgres"):
        backend = "auto"

    dsn = resolve_postgres_url(storage, app_gateway)

    from plugins.app_gateway.postgres_policy import (
        PostgresOnlyError,
        load_postgres_only_flag,
        reject_sqlite_backend,
        require_postgres_dsn,
    )

    pg_only = load_postgres_only_flag()
    if pg_only and db_path is not None:
        raise PostgresOnlyError(
            "session: postgres_only=true forbids explicit db_path (SQLite)"
        )

    if backend == "sqlite":
        if pg_only:
            raise PostgresOnlyError("session: postgres_only=true forbids session_backend=sqlite")
        return "sqlite", None
    if backend == "postgres":
        resolved = ("postgres", dsn) if dsn else ("sqlite", None)
        if pg_only and resolved[0] != "postgres":
            require_postgres_dsn(dsn, component="session")
        return resolved
    # auto
    if dsn:
        return "postgres", dsn
    if pg_only:
        require_postgres_dsn(dsn, component="session")
    return "sqlite", None


def _resolve_storage_backend(
    key: str,
    *,
    force_sqlite: bool = False,
) -> tuple[str, Optional[str]]:
    """Shared ``auto|sqlite|postgres`` resolution for kanban/cron backends."""
    if force_sqlite:
        return "sqlite", None
    storage, app_gateway = _load_storage_config()
    backend = str((storage or {}).get(key) or "auto").strip().lower()
    if backend not in ("auto", "sqlite", "postgres"):
        backend = "auto"
    dsn = resolve_postgres_url(storage, app_gateway)

    from plugins.app_gateway.postgres_policy import load_postgres_only_flag, require_postgres_dsn

    pg_only = load_postgres_only_flag()
    if backend == "sqlite":
        if pg_only:
            from plugins.app_gateway.postgres_policy import PostgresOnlyError

            raise PostgresOnlyError(f"{key}: postgres_only=true forbids {key}_backend=sqlite")
        return "sqlite", None
    if backend == "postgres":
        resolved = ("postgres", dsn) if dsn else ("sqlite", None)
        if pg_only and resolved[0] != "postgres":
            require_postgres_dsn(dsn, component=key)
        return resolved
    if dsn:
        return "postgres", dsn
    if pg_only:
        require_postgres_dsn(dsn, component=key)
    return "sqlite", None


def resolve_kanban_backend(db_path=None) -> Tuple[str, Optional[str]]:
    """Kanban uses PostgreSQL when configured unless ``db_path`` is explicit."""
    return _resolve_storage_backend("kanban_backend", force_sqlite=db_path is not None)


def resolve_cron_backend() -> Tuple[str, Optional[str]]:
    return _resolve_storage_backend("cron_backend")
