"""Process-wide PostgreSQL connection pool (multi-connection for 100+ concurrent agents)."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

_holders: dict[str, "_DsnHolder"] = {}
_pools: dict[str, "_DsnPool"] = {}
_registry_lock = threading.Lock()
_schema_init_done: set[str] = set()
_schema_lock = threading.Lock()


class _DsnHolder:
    """Legacy single connection (tests / schema bootstrap)."""

    __slots__ = ("dsn", "lock", "_conn")

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.lock = threading.RLock()
        self._conn: Any = None

    def connection(self) -> Any:
        if self._conn is None or getattr(self._conn, "closed", True):
            self._conn = _open_connection(self.dsn)
        return self._conn

    def close(self) -> None:
        with self.lock:
            if self._conn is not None and not getattr(self._conn, "closed", True):
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None


class _DsnPool:
    """Bounded pool — one checkout per concurrent agent DB operation."""

    __slots__ = ("dsn", "size", "_queue", "_conns")

    def __init__(self, dsn: str, size: int) -> None:
        self.dsn = dsn
        self.size = max(1, int(size))
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self.size)
        self._conns: list[Any] = []
        for _ in range(self.size):
            conn = _open_connection(dsn)
            self._conns.append(conn)
            self._queue.put(conn)

    @contextlib.contextmanager
    def borrow(self) -> Iterator[Any]:
        conn = self._queue.get()
        try:
            yield conn
        finally:
            self._queue.put(conn)

    def close(self) -> None:
        for conn in self._conns:
            try:
                if not getattr(conn, "closed", True):
                    conn.close()
            except Exception:
                pass
        self._conns.clear()


def _open_connection(dsn: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL requires psycopg. Install: uv pip install -e '.[postgres]'"
        ) from exc
    conn = psycopg.connect(
        dsn,
        row_factory=dict_row,
        autocommit=False,
        prepare_threshold=5,
    )
    with conn.cursor() as cur:
        cur.execute("SET application_name TO 'hermes-agent'")
        cur.execute("SET lock_timeout TO '5s'")
        cur.execute("SET statement_timeout TO '120s'")
    conn.commit()
    return conn


def resolve_postgres_pool_size() -> int:
    """Pool size from ``storage.postgres_pool_size`` (default 32)."""
    try:
        from hermes_cli.config import load_config

        raw = load_config() or {}
        storage = raw.get("storage") or {}
        if isinstance(storage, dict):
            val = storage.get("postgres_pool_size")
            if val is not None:
                return max(4, min(128, int(val)))
    except Exception:
        pass
    return 48


def holder_for(dsn: str) -> _DsnHolder:
    with _registry_lock:
        h = _holders.get(dsn)
        if h is None:
            h = _DsnHolder(dsn)
            _holders[dsn] = h
        return h


def pool_for(dsn: str, size: Optional[int] = None) -> _DsnPool:
    with _registry_lock:
        p = _pools.get(dsn)
        if p is None:
            p = _DsnPool(dsn, size or resolve_postgres_pool_size())
            _pools[dsn] = p
            logger.info("PostgreSQL pool for DSN: size=%s", p.size)
        return p


def mark_schema_initialized(dsn: str) -> None:
    with _schema_lock:
        _schema_init_done.add(dsn)


def schema_initialized(dsn: str) -> bool:
    with _schema_lock:
        return dsn in _schema_init_done


def try_create_extension(conn, name: str) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE EXTENSION IF NOT EXISTS {name}")
        conn.commit()
        return True
    except Exception as exc:
        logger.debug("PostgreSQL extension %s unavailable: %s", name, exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def reset_for_tests() -> None:
    """Close all pooled connections (tests only)."""
    with _registry_lock:
        for h in _holders.values():
            h.close()
        _holders.clear()
        for p in _pools.values():
            p.close()
        _pools.clear()
    with _schema_lock:
        _schema_init_done.clear()
