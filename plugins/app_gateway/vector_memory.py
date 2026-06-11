"""Per-user long-term memory (SQLite FTS5 namespace = user_id)."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from typing import Any, List, Optional

from plugins.app_gateway.user_scope import operator_app_gateway_root

logger = logging.getLogger(__name__)

_FTS_TOKEN = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def _fts_query(text: str) -> str:
    tokens = [t for t in _FTS_TOKEN.split((text or "").strip()) if len(t) >= 2]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens[:12])


class UserVectorMemory:
    """Namespace-isolated memory store (tgs.html: Vector NS per user)."""

    def __init__(self, enabled: bool = True, top_k: int = 5) -> None:
        self._enabled = enabled
        self._top_k = max(1, min(int(top_k), 20))
        self._lock = threading.Lock()
        self._path = operator_app_gateway_root() / "vector_memory.db"
        if enabled:
            self._init_db()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_entries(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    body,
                    content='memory_entries',
                    content_rowid='id',
                    tokenize='unicode61'
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self,
        user_id: str,
        session_id: str,
        body: str,
    ) -> None:
        if not self._enabled or not body or not user_id:
            return
        body = body.strip()
        if len(body) < 8:
            return
        with self._lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO memory_entries (user_id, session_id, body, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (user_id, session_id, body[:8000], time.time()),
                    )
                    rowid = cur.lastrowid
                    conn.execute(
                        "INSERT INTO memory_fts(rowid, body) VALUES (?, ?)",
                        (rowid, body[:8000]),
                    )
                    conn.commit()
            except Exception as exc:
                logger.debug("vector memory add failed: %s", exc)

    def search(self, user_id: str, query: str, *, limit: Optional[int] = None) -> List[str]:
        """Retrieve memories for *one* user only — cross-user reads are impossible by construction."""
        if not self._enabled or not user_id:
            return []
        limit = limit or self._top_k
        fts_q = _fts_query(query)
        with self._lock:
            try:
                with self._connect() as conn:
                    if fts_q:
                        rows = conn.execute(
                            """
                            SELECT e.body FROM memory_entries e
                            WHERE e.user_id = ?
                              AND e.id IN (
                                SELECT rowid FROM memory_fts WHERE memory_fts MATCH ?
                              )
                            ORDER BY e.created_at DESC
                            LIMIT ?
                            """,
                            (user_id, fts_q, limit),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """
                            SELECT body FROM memory_entries
                            WHERE user_id = ?
                            ORDER BY created_at DESC
                            LIMIT ?
                            """,
                            (user_id, limit),
                        ).fetchall()
                    return [r["body"] for r in rows]
            except Exception as exc:
                logger.debug("vector memory search failed: %s", exc)
                return []

    def list_recent(self, user_id: str, *, limit: int = 200) -> List[str]:
        if not self._enabled or not user_id:
            return []
        limit = max(1, min(int(limit), 500))
        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT body FROM memory_entries
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (user_id, limit),
                    ).fetchall()
                    return [r["body"] for r in rows]
            except Exception as exc:
                logger.debug("vector memory list_recent failed: %s", exc)
                return []

    def delete_user(self, user_id: str) -> int:
        if not self._enabled or not user_id:
            return 0
        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT id FROM memory_entries WHERE user_id = ?",
                        (user_id,),
                    ).fetchall()
                    ids = [int(r["id"]) for r in rows]
                    for rowid in ids:
                        conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (rowid,))
                    cur = conn.execute(
                        "DELETE FROM memory_entries WHERE user_id = ?",
                        (user_id,),
                    )
                    conn.commit()
                    return int(cur.rowcount or 0)
            except Exception as exc:
                logger.debug("vector memory delete_user failed: %s", exc)
                return 0

    def format_prefetch_block(self, user_id: str, query: str) -> str:
        hits = self.search(user_id, query)
        if not hits:
            return ""
        lines = "\n".join(f"- {h}" for h in hits)
        return (
            "[Recalled long-term memory for this user — not new user input]\n"
            f"{lines}\n"
        )

    def summarize_turn(self, user_message: str, assistant_message: str) -> str:
        """Compact turn summary for storage (no extra LLM call in phase 2)."""
        u = (user_message or "").strip().replace("\n", " ")
        a = (assistant_message or "").strip().replace("\n", " ")
        if len(u) > 400:
            u = u[:400] + "…"
        if len(a) > 600:
            a = a[:600] + "…"
        return f"User: {u}\nAssistant: {a}"


def create_user_vector_memory(config: Any) -> Any:
    """Return SQLite or PostgreSQL vector memory per ``app_gateway`` config.

    * ``vector_memory_backend: auto`` — use PostgreSQL when ``postgres_url``
      is set (requires ``psycopg``), else SQLite.
    * ``vector_memory_backend: postgres`` — require PostgreSQL.
    * ``vector_memory_backend: sqlite`` — always SQLite file under HERMES_HOME.
    """
    from plugins.app_gateway.config import AppGatewayConfig as _Cfg

    if not isinstance(config, _Cfg):
        raise TypeError("config must be AppGatewayConfig")

    backend = (getattr(config, "vector_memory_backend", None) or "auto").strip().lower()
    dsn = (getattr(config, "postgres_url", None) or "").strip()
    enabled = bool(getattr(config, "vector_memory_enabled", True))
    top_k = int(getattr(config, "vector_memory_top_k", 5) or 5)
    pg_only = bool(getattr(config, "postgres_only", False))

    from plugins.app_gateway.postgres_policy import load_postgres_only_flag, require_postgres_dsn

    pg_only = pg_only or load_postgres_only_flag()
    if pg_only and backend == "sqlite":
        from plugins.app_gateway.postgres_policy import PostgresOnlyError

        raise PostgresOnlyError(
            "vector_memory: postgres_only=true forbids vector_memory_backend=sqlite"
        )

    want_pg = backend == "postgres" or (backend == "auto" and bool(dsn)) or pg_only
    if want_pg:
        require_postgres_dsn(dsn, component="vector_memory")
        try:
            from plugins.app_gateway.postgres_vector_memory import PostgresUserVectorMemory

            return PostgresUserVectorMemory(dsn, enabled=enabled, top_k=top_k)
        except Exception as exc:
            if backend == "postgres" or pg_only:
                raise
            logger.warning(
                "PostgreSQL vector memory unavailable (%s); using SQLite", exc
            )

    if backend == "postgres" and not dsn:
        if pg_only:
            require_postgres_dsn(dsn, component="vector_memory")
        logger.warning("vector_memory_backend=postgres but postgres_url empty; using SQLite")

    if pg_only:
        from plugins.app_gateway.postgres_policy import PostgresOnlyError

        raise PostgresOnlyError(
            "vector_memory: postgres_only=true requires PostgreSQL vector memory"
        )

    return UserVectorMemory(enabled=enabled, top_k=top_k)
