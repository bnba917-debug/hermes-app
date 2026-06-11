"""Resolve and construct app user registry (SQLite or PostgreSQL)."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Tuple, Union

from plugins.app_gateway.user_scope import operator_app_gateway_root

logger = logging.getLogger(__name__)

RegistryImpl = Union["SqliteUserRegistry", "PostgresUserRegistry"]  # noqa: F821


def resolve_user_registry_backend() -> Tuple[str, Optional[str]]:
    """Return ``(backend, dsn)`` where backend is ``sqlite`` or ``postgres``."""
    from plugins.app_gateway.postgres_policy import load_postgres_only_flag

    backend = "auto"
    dsn = ""
    try:
        from plugins.app_gateway.config import load_app_gateway_config

        cfg = load_app_gateway_config()
        backend = str(cfg.user_registry_backend or "auto").strip().lower()
        dsn = str(cfg.postgres_url or "").strip()
    except Exception:
        pass

    if backend not in ("auto", "sqlite", "postgres"):
        backend = "auto"

    if not dsn:
        try:
            from agent.session_storage.config import resolve_postgres_url

            dsn = resolve_postgres_url()
        except Exception:
            dsn = ""

    if backend == "sqlite":
        if load_postgres_only_flag():
            from plugins.app_gateway.postgres_policy import PostgresOnlyError

            raise PostgresOnlyError("user_registry: postgres_only=true forbids sqlite backend")
        return "sqlite", None
    if backend == "postgres":
        if not dsn:
            if load_postgres_only_flag():
                from plugins.app_gateway.postgres_policy import require_postgres_dsn

                require_postgres_dsn(dsn, component="user_registry")
            return "sqlite", None
        return "postgres", dsn
    if dsn:
        return "postgres", dsn
    if load_postgres_only_flag():
        from plugins.app_gateway.postgres_policy import PostgresOnlyError, require_postgres_dsn

        require_postgres_dsn(dsn, component="user_registry")
        raise PostgresOnlyError(
            "user_registry: postgres_only=true requires PostgreSQL backend"
        )
    return "sqlite", None


def create_user_registry(
    *,
    backend: Optional[str] = None,
    dsn: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> RegistryImpl:
    """Build a registry implementation (used by :func:`get_user_registry`)."""
    from plugins.app_gateway.postgres_policy import PostgresOnlyError, load_postgres_only_flag

    resolved_backend, resolved_dsn = resolve_user_registry_backend()
    if backend is None:
        backend = resolved_backend
    if dsn is None:
        dsn = resolved_dsn

    if backend == "postgres" and dsn:
        from plugins.app_gateway.postgres_user_registry import PostgresUserRegistry

        reg = PostgresUserRegistry(dsn)
        _maybe_migrate_sqlite_to_postgres(reg, dsn)
        return reg

    if load_postgres_only_flag():
        raise PostgresOnlyError(
            "user_registry: postgres_only=true forbids SQLite user registry"
        )

    from plugins.app_gateway.user_registry import SqliteUserRegistry

    return SqliteUserRegistry(db_path=db_path)


def _maybe_migrate_sqlite_to_postgres(
    pg_registry: "PostgresUserRegistry",
    dsn: str,
) -> None:
    """One-time copy from legacy ``users_registry.db`` when PG tables are empty."""
    sqlite_path = operator_app_gateway_root() / "users_registry.db"
    if not sqlite_path.is_file():
        return
    marker = operator_app_gateway_root() / ".users_registry_sqlite_migrated"
    if marker.is_file():
        return

    try:
        import psycopg
    except ImportError:
        return

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM hermes_app_users")
            if int(cur.fetchone()[0]) > 0:
                marker.write_text("skipped-nonempty", encoding="utf-8")
                return

    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    try:
        users = src.execute("SELECT * FROM app_users").fetchall()
        otps = src.execute("SELECT * FROM sms_otp").fetchall()
    finally:
        src.close()

    if not users and not otps:
        marker.write_text("empty", encoding="utf-8")
        return

    migrated_users = 0
    migrated_otps = 0
    try:
        import psycopg
    except ImportError:
        return

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for row in users:
                pg_registry.upsert_user(str(row["user_id"]), str(row["phone"]))
                if row["initialized_at"]:
                    cur.execute(
                        """
                        UPDATE hermes_app_users
                        SET initialized_at = %s
                        WHERE user_id = %s
                        """,
                        (float(row["initialized_at"]), str(row["user_id"])),
                    )
                migrated_users += 1
            conn.commit()
    for row in otps:
        ttl = max(1, int(float(row["expires_at"]) - float(row["created_at"])))
        pg_registry.store_otp(str(row["phone"]), str(row["code"]), ttl_seconds=ttl)
        migrated_otps += 1

    marker.write_text(f"users={migrated_users},otps={migrated_otps}", encoding="utf-8")
    logger.info(
        "Migrated app user registry from SQLite to PostgreSQL (%d users, %d otps)",
        migrated_users,
        migrated_otps,
    )


_registry: Optional[RegistryImpl] = None
_registry_lock = threading.Lock()


def get_user_registry() -> RegistryImpl:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = create_user_registry()
        return _registry


def reset_user_registry_cache() -> None:
    """Tests only — force re-resolution on next :func:`get_user_registry`."""
    global _registry
    with _registry_lock:
        _registry = None
