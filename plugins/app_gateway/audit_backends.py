"""Audit backends: SQLite (default) and optional PostgreSQL."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from plugins.app_gateway.user_scope import operator_app_gateway_root

logger = logging.getLogger(__name__)


class AuditBackend(ABC):
    @abstractmethod
    def log(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: str,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...


class SqliteAuditBackend(AuditBackend):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path = operator_app_gateway_root() / "audit.db"
        self._init_db()

    def _init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    payload TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_user_ts ON audit_events(user_id, ts)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path), timeout=30)

    def log(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: str,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = (
            time.time(),
            user_id,
            session_id,
            device_id,
            event_type,
            json.dumps(payload or {}, ensure_ascii=False),
        )
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO audit_events
                            (ts, user_id, session_id, device_id, event_type, payload)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        row,
                    )
                    conn.commit()
            except Exception as exc:
                logger.debug("sqlite audit write failed: %s", exc)


class PostgresAuditBackend(AuditBackend):
    """PostgreSQL audit store (requires ``psycopg`` — ``pip install 'psycopg[binary]'``)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL audit requires psycopg. Install: pip install 'psycopg[binary]'"
            ) from exc
        return psycopg.connect(self._dsn)

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS hermes_audit_events (
                            id BIGSERIAL PRIMARY KEY,
                            ts DOUBLE PRECISION NOT NULL,
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            device_id TEXT,
                            event_type TEXT NOT NULL,
                            payload JSONB
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_hermes_audit_user_ts
                        ON hermes_audit_events (user_id, ts DESC)
                        """
                    )
                conn.commit()

    def log(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: str,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO hermes_audit_events
                                (ts, user_id, session_id, device_id, event_type, payload)
                            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                            """,
                            (
                                time.time(),
                                user_id,
                                session_id,
                                device_id,
                                event_type,
                                json.dumps(payload or {}, ensure_ascii=False),
                            ),
                        )
                    conn.commit()
            except Exception as exc:
                logger.warning("postgres audit write failed: %s", exc)


class CompositeAuditBackend(AuditBackend):
    """Write to multiple backends (e.g. sqlite + postgres)."""

    def __init__(self, backends: List[AuditBackend]) -> None:
        self._backends = backends

    def log(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: str,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        for backend in self._backends:
            backend.log(
                user_id=user_id,
                session_id=session_id,
                event_type=event_type,
                device_id=device_id,
                payload=payload,
            )


def create_audit_backend(
    backend: str,
    *,
    enabled: bool = True,
    postgres_url: str = "",
    postgres_only: bool = False,
) -> Optional[AuditBackend]:
    if not enabled:
        return None
    from plugins.app_gateway.postgres_policy import (
        PostgresOnlyError,
        load_postgres_only_flag,
        normalize_audit_backend_name,
        require_postgres_dsn,
    )

    pg_only = bool(postgres_only or load_postgres_only_flag())
    try:
        name = normalize_audit_backend_name(backend) if pg_only else (backend or "sqlite").strip().lower()
    except PostgresOnlyError:
        raise

    def _sqlite() -> SqliteAuditBackend:
        if pg_only:
            raise PostgresOnlyError("audit: postgres_only=true forbids SQLite audit backend")
        return SqliteAuditBackend()

    if name == "auto":
        if postgres_url:
            try:
                return PostgresAuditBackend(postgres_url)
            except Exception as exc:
                if pg_only:
                    raise RuntimeError(
                        f"audit: postgres_only=true but PostgreSQL audit failed: {exc}"
                    ) from exc
                logger.warning("PostgreSQL audit unavailable (%s); using sqlite", exc)
        if pg_only:
            require_postgres_dsn(postgres_url, component="audit")
        return _sqlite()
    if name == "sqlite":
        return _sqlite()
    if name == "postgres":
        if not postgres_url:
            if pg_only:
                require_postgres_dsn(postgres_url, component="audit")
            logger.warning("audit_backend=postgres but postgres_url empty; using sqlite")
            return _sqlite()
        return PostgresAuditBackend(postgres_url)
    if name in ("dual", "both"):
        if pg_only:
            raise PostgresOnlyError("audit: postgres_only=true forbids dual audit backends")
        backends: List[AuditBackend] = [_sqlite()]
        if postgres_url:
            try:
                backends.append(PostgresAuditBackend(postgres_url))
            except Exception as exc:
                logger.warning("PostgreSQL audit unavailable: %s", exc)
        return CompositeAuditBackend(backends)
    if pg_only:
        raise PostgresOnlyError(f"audit: unknown audit_backend {backend!r}")
    logger.warning("Unknown audit_backend %r; using sqlite", backend)
    return _sqlite()
