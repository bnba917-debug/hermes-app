"""SQLite-compatible connection wrapper for Kanban on PostgreSQL."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Iterable, Optional, Sequence, Tuple, Union

from agent.kanban_storage.postgres_schema import PG_KANBAN_DDL, pg_schema_name

logger = logging.getLogger(__name__)

Params = Union[Sequence[Any], Tuple[Any, ...]]

_INSERT_OR_IGNORE_CONFLICT = {
    "task_links": ("parent_id", "child_id"),
    "kanban_notify_subs": ("task_id", "platform", "chat_id", "thread_id"),
}

_AUTO_ID_TABLES = frozenset({"task_comments", "task_events", "task_runs"})


def _translate_sql(sql: str) -> str:
    text = sql.strip()
    upper = text.upper()

    if upper.startswith("PRAGMA"):
        return text

    text = re.sub(r"\bBEGIN\s+IMMEDIATE\b", "BEGIN", text, flags=re.IGNORECASE)
    text = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", text, flags=re.IGNORECASE)

    for table, cols in _INSERT_OR_IGNORE_CONFLICT.items():
        pat = rf"\bINSERT\s+OR\s+IGNORE\s+INTO\s+{table}\b"
        if re.search(pat, text, flags=re.IGNORECASE):
            text = re.sub(pat, f"INSERT INTO {table}", text, flags=re.IGNORECASE)
            if "ON CONFLICT" not in upper:
                col_list = ", ".join(cols)
                text = text.rstrip().rstrip(";") + f" ON CONFLICT ({col_list}) DO NOTHING"
            break

    if "?" in text:
        text = text.replace("?", "%s")
    return text


def _needs_returning_id(sql: str) -> bool:
    upper = sql.strip().upper()
    if not upper.startswith("INSERT"):
        return False
    for table in _AUTO_ID_TABLES:
        if re.search(rf"\bINTO\s+{table}\b", upper):
            return True
    return False


def _pragma_table_info(sql: str, schema: str, conn) -> list[dict]:
    m = re.search(r'PRAGMA\s+table_info\(["\']?(\w+)["\']?\)', sql, re.I)
    if not m:
        return []
    table = m.group(1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name AS name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [{"name": r[0]} for r in cur.fetchall()]


def _sqlite_master_check(sql: str, schema: str, conn) -> Optional[dict]:
    m = re.search(
        r"sqlite_master\s+WHERE\s+type\s*=\s*'table'\s+AND\s+name\s*=\s*'(\w+)'",
        sql,
        re.I,
    )
    if not m:
        return None
    table = m.group(1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename AS name FROM pg_tables
            WHERE schemaname = %s AND tablename = %s
            """,
            (schema, table),
        )
        row = cur.fetchone()
    return {"name": row[0]} if row else None


class PostgresKanbanCursor:
    """Subset of :class:`sqlite3.Cursor` used by ``kanban_db``."""

    def __init__(self, rows: list, lastrowid: Optional[int], rowcount: int) -> None:
        self._rows = rows
        self._index = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        rest = self._rows[self._index :]
        self._index = len(self._rows)
        return rest


class PostgresKanbanConnection:
    """Kanban DB connection backed by PostgreSQL (one schema per board)."""

    def __init__(self, dsn: str, board_slug: str) -> None:
        self._dsn = dsn
        self._board = board_slug
        self._schema = pg_schema_name(board_slug)
        self._lock = threading.RLock()
        self._conn = None
        self._init_schema_once()

    def _connect(self):
        if self._conn is None or self._conn.closed:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL kanban requires psycopg. Install: uv pip install -e '.[postgres]'"
                ) from exc
            self._conn = psycopg.connect(self._dsn, row_factory=dict_row, autocommit=False)
            with self._conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self._schema}"')
                cur.execute(f'SET search_path TO "{self._schema}"')
            self._conn.commit()
        return self._conn

    def _init_schema_once(self) -> None:
        with self._lock:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self._schema}"')
                for stmt in PG_KANBAN_DDL.split(";"):
                    chunk = stmt.strip()
                    if chunk:
                        cur.execute(chunk)
            conn.commit()

    def execute(self, sql: str, params: Params = ()):
        raw = sql.strip()
        upper = raw.upper()

        if upper.startswith("PRAGMA TABLE_INFO"):
            rows = _pragma_table_info(raw, self._schema, self._connect())
            return PostgresKanbanCursor(rows, None, len(rows))

        if "SQLITE_MASTER" in upper:
            row = _sqlite_master_check(raw, self._schema, self._connect())
            rows = [row] if row else []
            return PostgresKanbanCursor(rows, None, len(rows))

        if upper.startswith("PRAGMA"):
            return PostgresKanbanCursor([], None, 0)

        translated = _translate_sql(raw)
        returning = _needs_returning_id(translated)
        if returning and "RETURNING" not in translated.upper():
            translated = translated.rstrip().rstrip(";") + " RETURNING id"

        with self._lock:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(translated, params or ())
                rows: list = []
                lastrowid = None
                if returning:
                    one = cur.fetchone()
                    if one:
                        lastrowid = one.get("id")
                        rows = [one]
                elif cur.description:
                    rows = list(cur.fetchall())
                return PostgresKanbanCursor(rows, lastrowid, cur.rowcount)

    def executescript(self, script: str) -> None:
        with self._lock:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self._schema}"')
                for stmt in script.split(";"):
                    chunk = stmt.strip()
                    if chunk and not chunk.upper().startswith("PRAGMA"):
                        cur.execute(_translate_sql(chunk))
            conn.commit()

    def commit(self) -> None:
        with self._lock:
            if self._conn and not self._conn.closed:
                self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            if self._conn and not self._conn.closed:
                self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            if self._conn and not self._conn.closed:
                self._conn.close()
            self._conn = None


_CONNECTIONS: dict[tuple[str, str], PostgresKanbanConnection] = {}
_CONN_LOCK = threading.RLock()


def postgres_connect(dsn: str, *, board: str) -> PostgresKanbanConnection:
    """Open a Kanban board on PostgreSQL (schema ``kanban_<slug>``), cached per process."""
    slug = (board or "default").strip().lower()
    key = (dsn, slug)
    with _CONN_LOCK:
        conn = _CONNECTIONS.get(key)
        if conn is None:
            conn = PostgresKanbanConnection(dsn, slug)
            _CONNECTIONS[key] = conn
        return conn
