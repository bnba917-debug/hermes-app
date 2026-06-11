"""App Gateway long-term memory backed by PostgreSQL (per-user isolation)."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def _search_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.split((text or "").strip()) if len(t) >= 2][:12]


class PostgresUserVectorMemory:
    """Same contract as :class:`vector_memory.UserVectorMemory` — PostgreSQL storage."""

    def __init__(self, dsn: str, enabled: bool = True, top_k: int = 5) -> None:
        self._dsn = dsn
        self._enabled = enabled
        self._top_k = max(1, min(int(top_k), 20))
        self._lock = threading.Lock()
        if enabled and dsn:
            self._init_db()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL vector memory requires psycopg. "
                "Install: uv pip install -e '.[postgres]'"
            ) from exc
        return psycopg.connect(self._dsn)

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS hermes_app_memory_entries (
                            id BIGSERIAL PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            body TEXT NOT NULL,
                            created_at DOUBLE PRECISION NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_hermes_app_mem_user_created
                        ON hermes_app_memory_entries (user_id, created_at DESC)
                        """
                    )
                conn.commit()

    def add(self, user_id: str, session_id: str, body: str) -> None:
        if not self._enabled or not body or not user_id:
            return
        body = body.strip()
        if len(body) < 8:
            return
        body = body[:8000]
        with self._lock:
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO hermes_app_memory_entries
                                (user_id, session_id, body, created_at)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (user_id, session_id, body, time.time()),
                        )
                    conn.commit()
            except Exception as exc:
                logger.debug("postgres vector memory add failed: %s", exc)

    def search(self, user_id: str, query: str, *, limit: Optional[int] = None) -> List[str]:
        if not self._enabled or not user_id:
            return []
        limit = limit or self._top_k
        tokens = _search_tokens(query)
        with self._lock:
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        if tokens:
                            cond = " OR ".join(["body ILIKE %s"] * len(tokens))
                            params: list = [user_id] + [f"%{t}%" for t in tokens] + [limit]
                            cur.execute(
                                f"""
                                SELECT body FROM hermes_app_memory_entries
                                WHERE user_id = %s AND ({cond})
                                ORDER BY created_at DESC
                                LIMIT %s
                                """,
                                params,
                            )
                        else:
                            cur.execute(
                                """
                                SELECT body FROM hermes_app_memory_entries
                                WHERE user_id = %s
                                ORDER BY created_at DESC
                                LIMIT %s
                                """,
                                (user_id, limit),
                            )
                        return [r[0] for r in cur.fetchall()]
            except Exception as exc:
                logger.debug("postgres vector memory search failed: %s", exc)
                return []

    def list_recent(self, user_id: str, *, limit: int = 200) -> list:
        return self.search(user_id, "", limit=limit)

    def delete_user(self, user_id: str) -> int:
        if not self._enabled or not user_id:
            return 0
        with self._lock:
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "DELETE FROM hermes_app_memory_entries WHERE user_id = %s",
                            (user_id,),
                        )
                        deleted = cur.rowcount or 0
                    conn.commit()
                    return int(deleted)
            except Exception as exc:
                logger.debug("postgres vector memory delete_user failed: %s", exc)
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
        u = (user_message or "").strip().replace("\n", " ")
        a = (assistant_message or "").strip().replace("\n", " ")
        if len(u) > 400:
            u = u[:400] + "…"
        if len(a) > 600:
            a = a[:600] + "…"
        return f"User: {u}\nAssistant: {a}"
