"""PostgreSQL session store — API-compatible with :class:`hermes_state.SessionDB`."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from agent.memory_manager import sanitize_context
from agent.session_storage.base import SessionStoreBase
from agent.session_storage.postgres_pool import (
    mark_schema_initialized,
    pool_for,
    schema_initialized,
    try_create_extension,
)
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

T = TypeVar("T")

SCHEMA_VERSION = 11

_instances: Dict[str, "PostgresSessionDB"] = {}
_instances_lock = threading.Lock()


def get_postgres_session_db(dsn: str) -> "PostgresSessionDB":
    """One store instance per DSN per process (shared connection, like SQLite ``SessionDB``)."""
    with _instances_lock:
        inst = _instances.get(dsn)
        if inst is None:
            inst = PostgresSessionDB(dsn)
            _instances[dsn] = inst
        return inst

_PREVIEW_SUBQ = """
    COALESCE(
        (SELECT SUBSTRING(REPLACE(REPLACE(m.content, E'\\n', ' '), E'\\r', ' ') FROM 1 FOR 63)
         FROM messages m
         WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
         ORDER BY m.timestamp, m.id LIMIT 1),
        ''
    )
"""

_LAST_ACTIVE_SUBQ = """
    COALESCE(
        (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
        s.started_at
    )
"""


class PostgresSessionDB(SessionStoreBase):
    """PostgreSQL-backed session storage (requires ``psycopg``)."""

    backend = "postgres"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = pool_for(dsn)
        self.db_path = get_hermes_home() / "state.db"
        self._init_schema()

    @contextlib.contextmanager
    def _with_conn(self):
        with self._pool.borrow() as conn:
            yield conn

    def _init_schema(self) -> None:
        if schema_initialized(self._dsn):
            return
        ddl = """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT REFERENCES sessions(id),
            started_at DOUBLE PRECISION NOT NULL,
            ended_at DOUBLE PRECISION,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd DOUBLE PRECISION,
            actual_cost_usd DOUBLE PRECISION,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            api_call_count INTEGER DEFAULT 0,
            handoff_state TEXT,
            handoff_platform TEXT,
            handoff_error TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp DOUBLE PRECISION NOT NULL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT
        );
        CREATE TABLE IF NOT EXISTS state_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
        CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_messages_search_gin ON messages USING gin(
            to_tsvector(
                'simple',
                coalesce(content, '') || ' ' || coalesce(tool_name, '') || ' ' || coalesce(tool_calls, '')
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique
            ON sessions(title) WHERE title IS NOT NULL;
        CREATE TABLE IF NOT EXISTS telegram_dm_topic_mode (
            chat_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS telegram_dm_topic_bindings (
            chat_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_key TEXT NOT NULL,
            session_id TEXT NOT NULL UNIQUE,
            managed_mode TEXT NOT NULL DEFAULT 'auto',
            linked_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (chat_id, thread_id)
        );
        CREATE INDEX IF NOT EXISTS idx_telegram_dm_topic_bindings_user
            ON telegram_dm_topic_bindings(user_id, chat_id);
        """
        with self._pool.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
                cur.execute("SELECT version FROM schema_version LIMIT 1")
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        "INSERT INTO schema_version (version) VALUES (%s)",
                        (SCHEMA_VERSION,),
                    )
                elif row["version"] < SCHEMA_VERSION:
                    cur.execute(
                        "UPDATE schema_version SET version = %s",
                        (SCHEMA_VERSION,),
                    )
            conn.commit()
            if try_create_extension(conn, "pg_trgm"):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_messages_search_trgm ON messages USING gin(
                            (coalesce(content, '') || ' ' || coalesce(tool_name, '')
                             || ' ' || coalesce(tool_calls, '')) gin_trgm_ops
                        )
                        """
                    )
                conn.commit()
        mark_schema_initialized(self._dsn)

    def _execute_write(self, fn: Callable[..., T]) -> T:
        with self._pool.borrow() as conn:
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        pass

    def vacuum(self) -> None:
        pass

    @staticmethod
    def _encode_content(content: Any) -> Any:
        if isinstance(content, (list, dict)):
            return json.dumps(content, ensure_ascii=False)
        return content

    @classmethod
    def _decode_content(cls, content: Any) -> Any:
        if isinstance(content, str) and content and content[0] in ("[", "{"):
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return content
        return content

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        from hermes_state import SessionDB

        return SessionDB.sanitize_title(title)

    # ── lifecycle ─────────────────────────────────────────────────────

    def _insert_session_row(
        self,
        session_id: str,
        source: str,
        model: str = None,
        model_config: Dict[str, Any] = None,
        system_prompt: str = None,
        user_id: str = None,
        parent_session_id: str = None,
    ) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (
                        id, source, user_id, model, model_config, system_prompt,
                        parent_session_id, started_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        session_id,
                        source,
                        user_id,
                        model,
                        json.dumps(model_config) if model_config else None,
                        system_prompt,
                        parent_session_id,
                        time.time(),
                    ),
                )

        self._execute_write(_do)

    def create_session(self, session_id: str, source: str, **kwargs) -> str:
        self._insert_session_row(session_id, source, **kwargs)
        return session_id

    def ensure_session(
        self, session_id: str, source: str = "unknown", model: str = None, **kwargs
    ) -> str:
        self._insert_session_row(session_id, source, model=model, **kwargs)
        return session_id

    def end_session(self, session_id: str, end_reason: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions SET ended_at = %s, end_reason = %s
                    WHERE id = %s AND ended_at IS NULL
                    """,
                    (time.time(), end_reason, session_id),
                )

        self._execute_write(_do)

    def reopen_session(self, session_id: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET ended_at = NULL, end_reason = NULL WHERE id = %s",
                    (session_id,),
                )

        self._execute_write(_do)

    def update_system_prompt(self, session_id: str, system_prompt: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET system_prompt = %s WHERE id = %s",
                    (system_prompt, session_id),
                )

        self._execute_write(_do)

    def update_token_counts(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        estimated_cost_usd: Optional[float] = None,
        actual_cost_usd: Optional[float] = None,
        cost_status: Optional[str] = None,
        cost_source: Optional[str] = None,
        pricing_version: Optional[str] = None,
        billing_provider: Optional[str] = None,
        billing_base_url: Optional[str] = None,
        billing_mode: Optional[str] = None,
        api_call_count: int = 0,
        absolute: bool = False,
    ) -> None:
        self._insert_session_row(session_id, "unknown", model=model)
        if absolute:
            sql = """
                UPDATE sessions SET
                   input_tokens = %s, output_tokens = %s,
                   cache_read_tokens = %s, cache_write_tokens = %s,
                   reasoning_tokens = %s,
                   estimated_cost_usd = COALESCE(%s, 0),
                   actual_cost_usd = CASE WHEN %s IS NULL THEN actual_cost_usd ELSE %s END,
                   cost_status = COALESCE(%s, cost_status),
                   cost_source = COALESCE(%s, cost_source),
                   pricing_version = COALESCE(%s, pricing_version),
                   billing_provider = COALESCE(billing_provider, %s),
                   billing_base_url = COALESCE(billing_base_url, %s),
                   billing_mode = COALESCE(billing_mode, %s),
                   model = COALESCE(model, %s),
                   api_call_count = %s
                WHERE id = %s
            """
        else:
            sql = """
                UPDATE sessions SET
                   input_tokens = input_tokens + %s,
                   output_tokens = output_tokens + %s,
                   cache_read_tokens = cache_read_tokens + %s,
                   cache_write_tokens = cache_write_tokens + %s,
                   reasoning_tokens = reasoning_tokens + %s,
                   estimated_cost_usd = COALESCE(estimated_cost_usd, 0) + COALESCE(%s, 0),
                   actual_cost_usd = CASE
                       WHEN %s IS NULL THEN actual_cost_usd
                       ELSE COALESCE(actual_cost_usd, 0) + %s END,
                   cost_status = COALESCE(%s, cost_status),
                   cost_source = COALESCE(%s, cost_source),
                   pricing_version = COALESCE(%s, pricing_version),
                   billing_provider = COALESCE(billing_provider, %s),
                   billing_base_url = COALESCE(billing_base_url, %s),
                   billing_mode = COALESCE(billing_mode, %s),
                   model = COALESCE(model, %s),
                   api_call_count = COALESCE(api_call_count, 0) + %s
                WHERE id = %s
            """
        params = (
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_write_tokens,
            reasoning_tokens,
            estimated_cost_usd,
            actual_cost_usd,
            actual_cost_usd,
            cost_status,
            cost_source,
            pricing_version,
            billing_provider,
            billing_base_url,
            billing_mode,
            model,
            api_call_count,
            session_id,
        )

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(sql, params)

        self._execute_write(_do)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
                    row = cur.fetchone()
        return dict(row) if row else None

    def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
        exact = self.get_session(session_id_or_prefix)
        if exact:
            return exact["id"]
        escaped = (
            session_id_or_prefix.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM sessions
                        WHERE id LIKE %s ESCAPE '\\'
                        ORDER BY started_at DESC LIMIT 2
                        """,
                        (f"{escaped}%",),
                    )
                    matches = [r["id"] for r in cur.fetchall()]
        if len(matches) == 1:
            return matches[0]
        return None

    def set_session_title(self, session_id: str, title: str) -> bool:
        title = self.sanitize_title(title)

        def _do(conn):
            with conn.cursor() as cur:
                if title:
                    cur.execute(
                        "SELECT id FROM sessions WHERE title = %s AND id != %s",
                        (title, session_id),
                    )
                    if cur.fetchone():
                        raise ValueError(f"Title already in use: {title}")
                cur.execute(
                    "UPDATE sessions SET title = %s WHERE id = %s",
                    (title, session_id),
                )
                return cur.rowcount > 0

        return bool(self._execute_write(_do))

    def get_session_title(self, session_id: str) -> Optional[str]:
        row = self.get_session(session_id)
        return row.get("title") if row else None

    def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM sessions WHERE title = %s", (title,))
                    row = cur.fetchone()
        return dict(row) if row else None

    def resolve_session_by_title(self, title: str) -> Optional[str]:
        row = self.get_session_by_title(title)
        return row["id"] if row else None

    def get_next_title_in_lineage(self, base_title: str) -> str:
        match = re.match(r"^(.*?) #(\d+)$", base_title)
        base = match.group(1) if match else base_title
        escaped = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT title FROM sessions
                        WHERE title = %s OR title LIKE %s ESCAPE '\\'
                        """,
                        (base, f"{escaped} #%"),
                    )
                    existing = [r["title"] for r in cur.fetchall()]
        if not existing:
            return base
        max_num = 1
        for t in existing:
            m = re.match(r"^.* #(\d+)$", t)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{base} #{max_num + 1}"

    def get_compression_tip(self, session_id: str) -> Optional[str]:
        current = session_id
        for _ in range(100):
            with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM sessions
                        WHERE parent_session_id = %s
                          AND started_at >= (
                              SELECT ended_at FROM sessions
                              WHERE id = %s AND end_reason = 'compression'
                          )
                        ORDER BY started_at DESC LIMIT 1
                        """,
                        (current, current),
                    )
                    row = cur.fetchone()
            if row is None:
                return current
            current = row["id"]
        return current

    # ── messages ──────────────────────────────────────────────────────

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str = None,
        tool_name: str = None,
        tool_calls: Any = None,
        tool_call_id: str = None,
        token_count: int = None,
        finish_reason: str = None,
        reasoning: str = None,
        reasoning_content: str = None,
        reasoning_details: Any = None,
        codex_reasoning_items: Any = None,
        codex_message_items: Any = None,
    ) -> int:
        reasoning_details_json = (
            json.dumps(reasoning_details) if reasoning_details else None
        )
        codex_items_json = (
            json.dumps(codex_reasoning_items) if codex_reasoning_items else None
        )
        codex_message_items_json = (
            json.dumps(codex_message_items) if codex_message_items else None
        )
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        stored_content = self._encode_content(content)
        num_tool_calls = (
            len(tool_calls) if isinstance(tool_calls, list) else 1
            if tool_calls is not None
            else 0
        )

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages (
                        session_id, role, content, tool_call_id, tool_calls, tool_name,
                        timestamp, token_count, finish_reason, reasoning, reasoning_content,
                        reasoning_details, codex_reasoning_items, codex_message_items
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        session_id,
                        role,
                        stored_content,
                        tool_call_id,
                        tool_calls_json,
                        tool_name,
                        time.time(),
                        token_count,
                        finish_reason,
                        reasoning,
                        reasoning_content,
                        reasoning_details_json,
                        codex_items_json,
                        codex_message_items_json,
                    ),
                )
                msg_id = cur.fetchone()["id"]
                if num_tool_calls > 0:
                    cur.execute(
                        """
                        UPDATE sessions SET message_count = message_count + 1,
                            tool_call_count = tool_call_count + %s WHERE id = %s
                        """,
                        (num_tool_calls, session_id),
                    )
                else:
                    cur.execute(
                        "UPDATE sessions SET message_count = message_count + 1 WHERE id = %s",
                        (session_id,),
                    )
                return msg_id

        return self._execute_write(_do)

    def append_messages_batch(
        self,
        session_id: str,
        rows: List[Dict[str, Any]],
    ) -> List[int]:
        """Append multiple messages in one transaction (one commit)."""
        if not rows:
            return []

        def _do(conn):
            ids: List[int] = []
            total_tool_calls = 0
            now_ts = time.time()
            with conn.cursor() as cur:
                for row in rows:
                    role = row.get("role", "unknown")
                    tool_calls = row.get("tool_calls")
                    reasoning_details = row.get("reasoning_details") if role == "assistant" else None
                    codex_reasoning_items = (
                        row.get("codex_reasoning_items") if role == "assistant" else None
                    )
                    codex_message_items = (
                        row.get("codex_message_items") if role == "assistant" else None
                    )
                    reasoning_details_json = (
                        json.dumps(reasoning_details) if reasoning_details else None
                    )
                    codex_items_json = (
                        json.dumps(codex_reasoning_items) if codex_reasoning_items else None
                    )
                    codex_message_items_json = (
                        json.dumps(codex_message_items) if codex_message_items else None
                    )
                    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
                    stored_content = self._encode_content(row.get("content"))
                    num_tool_calls = 0
                    if tool_calls is not None:
                        num_tool_calls = (
                            len(tool_calls) if isinstance(tool_calls, list) else 1
                        )
                    total_tool_calls += num_tool_calls

                    cur.execute(
                        """
                        INSERT INTO messages (
                            session_id, role, content, tool_call_id, tool_calls, tool_name,
                            timestamp, token_count, finish_reason, reasoning, reasoning_content,
                            reasoning_details, codex_reasoning_items, codex_message_items
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (
                            session_id,
                            role,
                            stored_content,
                            row.get("tool_call_id"),
                            tool_calls_json,
                            row.get("tool_name"),
                            now_ts,
                            row.get("token_count"),
                            row.get("finish_reason"),
                            row.get("reasoning") if role == "assistant" else None,
                            row.get("reasoning_content") if role == "assistant" else None,
                            reasoning_details_json,
                            codex_items_json,
                            codex_message_items_json,
                        ),
                    )
                    ids.append(int(cur.fetchone()["id"]))

                cur.execute(
                    """
                    UPDATE sessions SET message_count = message_count + %s,
                        tool_call_count = tool_call_count + %s WHERE id = %s
                    """,
                    (len(rows), total_tool_calls, session_id),
                )
            return ids

        return self._execute_write(_do)

    def replace_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
                cur.execute(
                    "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = %s",
                    (session_id,),
                )
                now_ts = time.time()
                total_messages = 0
                total_tool_calls = 0
                for msg in messages:
                    role = msg.get("role", "unknown")
                    tool_calls = msg.get("tool_calls")
                    cur.execute(
                        """
                        INSERT INTO messages (
                            session_id, role, content, tool_call_id, tool_calls, tool_name,
                            timestamp, token_count, finish_reason, reasoning, reasoning_content,
                            reasoning_details, codex_reasoning_items, codex_message_items
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            session_id,
                            role,
                            self._encode_content(msg.get("content")),
                            msg.get("tool_call_id"),
                            json.dumps(tool_calls) if tool_calls else None,
                            msg.get("tool_name"),
                            now_ts,
                            msg.get("token_count"),
                            msg.get("finish_reason"),
                            msg.get("reasoning") if role == "assistant" else None,
                            msg.get("reasoning_content") if role == "assistant" else None,
                            json.dumps(msg.get("reasoning_details"))
                            if role == "assistant" and msg.get("reasoning_details")
                            else None,
                            json.dumps(msg.get("codex_reasoning_items"))
                            if role == "assistant" and msg.get("codex_reasoning_items")
                            else None,
                            json.dumps(msg.get("codex_message_items"))
                            if role == "assistant" and msg.get("codex_message_items")
                            else None,
                        ),
                    )
                    total_messages += 1
                    if tool_calls is not None:
                        total_tool_calls += (
                            len(tool_calls) if isinstance(tool_calls, list) else 1
                        )
                    now_ts += 1e-6
                cur.execute(
                    "UPDATE sessions SET message_count = %s, tool_call_count = %s WHERE id = %s",
                    (total_messages, total_tool_calls, session_id),
                )

        self._execute_write(_do)

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM messages WHERE session_id = %s ORDER BY id",
                        (session_id,),
                    )
                    rows = cur.fetchall()
        result = []
        for row in rows:
            msg = dict(row)
            if "content" in msg:
                msg["content"] = self._decode_content(msg["content"])
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    msg["tool_calls"] = []
            result.append(msg)
        return result

    def get_messages_as_conversation(
        self, session_id: str, include_ancestors: bool = False
    ) -> List[Dict[str, Any]]:
        session_ids = [session_id]
        if include_ancestors:
            session_ids = self._session_lineage_root_to_tip(session_id)

        placeholders = ",".join("%s" for _ in session_ids)
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT role, content, tool_call_id, tool_calls, tool_name,
                               finish_reason, reasoning, reasoning_content, reasoning_details,
                               codex_reasoning_items, codex_message_items
                        FROM messages WHERE session_id IN ({placeholders}) ORDER BY id
                        """,
                        tuple(session_ids),
                    )
                    rows = cur.fetchall()

        messages = []
        for row in rows:
            content = self._decode_content(row["content"])
            if row["role"] in {"user", "assistant"} and isinstance(content, str):
                content = sanitize_context(content).strip()
            msg = {"role": row["role"], "content": content}
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            if row["tool_name"]:
                msg["tool_name"] = row["tool_name"]
            if row["tool_calls"]:
                try:
                    msg["tool_calls"] = json.loads(row["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    msg["tool_calls"] = []
            if row["role"] == "assistant":
                for key, col in (
                    ("finish_reason", "finish_reason"),
                    ("reasoning", "reasoning"),
                    ("reasoning_content", "reasoning_content"),
                ):
                    if row.get(col) is not None:
                        msg[key] = row[col]
                for key, col in (
                    ("reasoning_details", "reasoning_details"),
                    ("codex_reasoning_items", "codex_reasoning_items"),
                    ("codex_message_items", "codex_message_items"),
                ):
                    if row.get(col):
                        try:
                            msg[key] = json.loads(row[col])
                        except (json.JSONDecodeError, TypeError):
                            msg[key] = None
            if include_ancestors and self._is_duplicate_replayed_user_message(messages, msg):
                continue
            messages.append(msg)
        return messages

    @staticmethod
    def _is_duplicate_replayed_user_message(
        messages: List[Dict[str, Any]], msg: Dict[str, Any]
    ) -> bool:
        from hermes_state import SessionDB

        return SessionDB._is_duplicate_replayed_user_message(messages, msg)

    def _session_lineage_root_to_tip(self, session_id: str) -> List[str]:
        if not session_id:
            return [session_id]
        chain = []
        current = session_id
        seen = set()
        for _ in range(100):
            if not current or current in seen:
                break
            seen.add(current)
            chain.append(current)
            row = self.get_session(current)
            if not row or not row.get("parent_session_id"):
                break
            current = row["parent_session_id"]
        return chain

    def resolve_resume_session_id(self, session_id: str) -> str:
        if not session_id:
            return session_id
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM messages WHERE session_id = %s LIMIT 1",
                        (session_id,),
                    )
                    if cur.fetchone():
                        return session_id
                    current = session_id
                    seen = {current}
                    for _ in range(32):
                        cur.execute(
                            """
                            SELECT id FROM sessions
                            WHERE parent_session_id = %s
                            ORDER BY started_at DESC, id DESC LIMIT 1
                            """,
                            (current,),
                        )
                        child = cur.fetchone()
                        if not child:
                            return session_id
                        child_id = child["id"]
                        if child_id in seen:
                            return session_id
                        seen.add(child_id)
                        cur.execute(
                            "SELECT 1 FROM messages WHERE session_id = %s LIMIT 1",
                            (child_id,),
                        )
                        if cur.fetchone():
                            return child_id
                        current = child_id
        return session_id

    def get_messages_around(
        self,
        session_id: str,
        around_message_id: int,
        window: int = 5,
    ) -> Dict[str, Any]:
        if window < 0:
            window = 0
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM messages WHERE id = %s AND session_id = %s LIMIT 1",
                        (around_message_id, session_id),
                    )
                    if not cur.fetchone():
                        return {"window": [], "messages_before": 0, "messages_after": 0}
                    cur.execute(
                        """
                        SELECT * FROM messages
                        WHERE session_id = %s AND id <= %s
                        ORDER BY id DESC LIMIT %s
                        """,
                        (session_id, around_message_id, window + 1),
                    )
                    before_rows = cur.fetchall()
                    cur.execute(
                        """
                        SELECT * FROM messages
                        WHERE session_id = %s AND id > %s
                        ORDER BY id ASC LIMIT %s
                        """,
                        (session_id, around_message_id, window),
                    )
                    after_rows = cur.fetchall()

        rows = list(reversed(before_rows)) + list(after_rows)
        result = []
        for row in rows:
            msg = dict(row)
            if "content" in msg:
                msg["content"] = self._decode_content(msg["content"])
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    msg["tool_calls"] = []
            result.append(msg)
        return {
            "window": result,
            "messages_before": max(0, len(before_rows) - 1),
            "messages_after": len(after_rows),
        }

    def get_anchored_view(
        self,
        session_id: str,
        around_message_id: int,
        window: int = 5,
        bookend: int = 3,
        keep_roles: Optional[Tuple[str, ...]] = ("user", "assistant"),
    ) -> Dict[str, Any]:
        if bookend < 0:
            bookend = 0
        primitive = self.get_messages_around(session_id, around_message_id, window=window)
        window_rows = primitive["window"]
        if not window_rows:
            return {
                "window": [],
                "messages_before": 0,
                "messages_after": 0,
                "bookend_start": [],
                "bookend_end": [],
            }
        if keep_roles is not None:
            keep_set = set(keep_roles)
            filtered_window = [
                m
                for m in window_rows
                if m.get("id") == around_message_id or m.get("role") in keep_set
            ]
        else:
            filtered_window = window_rows
        window_min_id = window_rows[0]["id"]
        window_max_id = window_rows[-1]["id"]
        bookend_start_rows: List[Any] = []
        bookend_end_rows: List[Any] = []
        if bookend > 0:
            role_clause = ""
            role_params: list = []
            if keep_roles is not None:
                role_placeholders = ",".join("%s" for _ in keep_roles)
                role_clause = f" AND role IN ({role_placeholders})"
                role_params = list(keep_roles)
            with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT * FROM messages
                        WHERE session_id = %s AND id < %s{role_clause}
                          AND length(content) > 0
                        ORDER BY id ASC LIMIT %s
                        """,
                        (session_id, window_min_id, *role_params, bookend),
                    )
                    bookend_start_rows = cur.fetchall()
                    cur.execute(
                        f"""
                        SELECT * FROM messages
                        WHERE session_id = %s AND id > %s{role_clause}
                          AND length(content) > 0
                        ORDER BY id DESC LIMIT %s
                        """,
                        (session_id, window_max_id, *role_params, bookend),
                    )
                    bookend_end_rows = list(reversed(cur.fetchall()))

        def _hydrate(row) -> Dict[str, Any]:
            msg = dict(row)
            if "content" in msg:
                msg["content"] = self._decode_content(msg["content"])
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    msg["tool_calls"] = []
            return msg

        return {
            "window": filtered_window,
            "messages_before": primitive["messages_before"],
            "messages_after": primitive["messages_after"],
            "bookend_start": [_hydrate(r) for r in bookend_start_rows],
            "bookend_end": [_hydrate(r) for r in bookend_end_rows],
        }

    # ── search / list ─────────────────────────────────────────────────

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        from hermes_state import SessionDB

        return SessionDB._contains_cjk(text)

    def search_messages(
        self,
        query: str,
        source_filter: List[str] = None,
        exclude_sources: List[str] = None,
        role_filter: List[str] = None,
        limit: int = 20,
        offset: int = 0,
        sort: str = None,
    ) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []
        from hermes_state import SessionDB

        sanitized = SessionDB._sanitize_fts5_query(query)
        if not sanitized:
            return []
        raw = sanitized.strip().strip('"')
        sort_norm = None
        if isinstance(sort, str):
            sort_norm = sort.strip().lower()
            if sort_norm not in ("newest", "oldest"):
                sort_norm = None

        if sort_norm == "newest":
            order_sql = "ORDER BY m.timestamp DESC"
        elif sort_norm == "oldest":
            order_sql = "ORDER BY m.timestamp ASC"
        else:
            order_sql = "ORDER BY m.timestamp DESC"

        search_blob = (
            "coalesce(m.content,'') || ' ' || coalesce(m.tool_name,'') || ' ' "
            "|| coalesce(m.tool_calls,'')"
        )
        where = []
        params: list = []
        cjk_count = SessionDB._count_cjk(raw)
        if cjk_count >= 3 and not re.search(r"\b(AND|OR|NOT)\b", sanitized, re.I):
            where.append(f"{search_blob} ILIKE %s")
            params.append(f"%{raw}%")
        elif cjk_count >= 1:
            where.append(f"{search_blob} ILIKE %s")
            params.append(f"%{raw}%")
        else:
            where.append(f"to_tsvector('simple', {search_blob}) @@ plainto_tsquery('simple', %s)")
            params.append(raw)

        if source_filter is not None:
            where.append(f"s.source IN ({','.join('%s' for _ in source_filter)})")
            params.extend(source_filter)
        if exclude_sources is not None:
            where.append(f"s.source NOT IN ({','.join('%s' for _ in exclude_sources)})")
            params.extend(exclude_sources)
        if role_filter:
            where.append(f"m.role IN ({','.join('%s' for _ in role_filter)})")
            params.extend(role_filter)

        params.extend([limit, offset])
        sql = f"""
            SELECT m.id, m.session_id, m.role, m.content, m.timestamp, m.tool_name,
                   s.source, s.model, s.started_at AS session_started,
                   LEFT(m.content, 120) AS snippet
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE {' AND '.join(where)}
            {order_sql}
            LIMIT %s OFFSET %s
        """
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
        return [dict(r) for r in rows]

    def search_sessions(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        base = (
            "SELECT s.*, COALESCE(m.last_active, s.started_at) AS last_active "
            "FROM sessions s "
            "LEFT JOIN ("
            "SELECT session_id, MAX(timestamp) AS last_active "
            "FROM messages GROUP BY session_id"
            ") m ON m.session_id = s.id "
        )
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    if source:
                        cur.execute(
                            base
                            + "WHERE s.source = %s "
                            "ORDER BY last_active DESC, s.started_at DESC, s.id DESC "
                            "LIMIT %s OFFSET %s",
                            (source, limit, offset),
                        )
                    else:
                        cur.execute(
                            base
                            + "ORDER BY last_active DESC, s.started_at DESC, s.id DESC "
                            "LIMIT %s OFFSET %s",
                            (limit, offset),
                        )
                    return [dict(r) for r in cur.fetchall()]

    def list_sessions_rich(
        self,
        source: str = None,
        exclude_sources: List[str] = None,
        limit: int = 20,
        offset: int = 0,
        include_children: bool = False,
        project_compression_tips: bool = True,
        order_by_last_active: bool = False,
    ) -> List[Dict[str, Any]]:
        where_clauses = []
        params: list = []
        if not include_children:
            where_clauses.append(
                "(s.parent_session_id IS NULL OR EXISTS ("
                "SELECT 1 FROM sessions p WHERE p.id = s.parent_session_id "
                "AND p.end_reason = 'branched' AND s.started_at >= p.ended_at))"
            )
        if source:
            where_clauses.append("s.source = %s")
            params.append(source)
        if exclude_sources:
            where_clauses.append(
                f"s.source NOT IN ({','.join('%s' for _ in exclude_sources)})"
            )
            params.extend(exclude_sources)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        if order_by_last_active:
            query = f"""
                WITH RECURSIVE chain(root_id, cur_id) AS (
                    SELECT s.id, s.id FROM sessions s {where_sql}
                    UNION ALL
                    SELECT c.root_id, child.id
                    FROM chain c
                    JOIN sessions parent ON parent.id = c.cur_id
                    JOIN sessions child ON child.parent_session_id = c.cur_id
                    WHERE parent.end_reason = 'compression'
                      AND child.started_at >= parent.ended_at
                ),
                chain_max AS (
                    SELECT root_id,
                        MAX(COALESCE(
                            (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = cur_id),
                            (SELECT started_at FROM sessions ss WHERE ss.id = cur_id)
                        )) AS effective_last_active
                    FROM chain GROUP BY root_id
                )
                SELECT s.*, {_PREVIEW_SUBQ} AS _preview_raw,
                    {_LAST_ACTIVE_SUBQ} AS last_active,
                    COALESCE(cm.effective_last_active, s.started_at) AS _effective_last_active
                FROM sessions s
                LEFT JOIN chain_max cm ON cm.root_id = s.id
                {where_sql}
                ORDER BY _effective_last_active DESC, s.started_at DESC, s.id DESC
                LIMIT %s OFFSET %s
            """
            params = params + params + [limit, offset]
        else:
            query = f"""
                SELECT s.*, {_PREVIEW_SUBQ} AS _preview_raw,
                    {_LAST_ACTIVE_SUBQ} AS last_active
                FROM sessions s {where_sql}
                ORDER BY s.started_at DESC
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])

        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

        sessions = []
        for row in rows:
            s = dict(row)
            raw = str(s.pop("_preview_raw", "") or "").strip()
            s["preview"] = raw[:60] + ("..." if len(raw) > 60 else "") if raw else ""
            s.pop("_effective_last_active", None)
            sessions.append(s)

        if project_compression_tips and not include_children:
            projected = []
            for s in sessions:
                if s.get("end_reason") != "compression":
                    projected.append(s)
                    continue
                tip_id = self.get_compression_tip(s["id"])
                if tip_id == s["id"]:
                    projected.append(s)
                    continue
                tip_row = self._get_session_rich_row(tip_id)
                if not tip_row:
                    projected.append(s)
                    continue
                merged = dict(s)
                for key in (
                    "id",
                    "ended_at",
                    "end_reason",
                    "message_count",
                    "tool_call_count",
                    "title",
                    "last_active",
                    "preview",
                    "model",
                    "system_prompt",
                ):
                    if key in tip_row:
                        merged[key] = tip_row[key]
                merged["_lineage_root_id"] = s["id"]
                projected.append(merged)
            sessions = projected
        return sessions

    def _get_session_rich_row(self, session_id: str) -> Optional[Dict[str, Any]]:
        query = f"""
            SELECT s.*, {_PREVIEW_SUBQ} AS _preview_raw,
                {_LAST_ACTIVE_SUBQ} AS last_active
            FROM sessions s WHERE s.id = %s
        """
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (session_id,))
                    row = cur.fetchone()
        if not row:
            return None
        s = dict(row)
        raw = str(s.pop("_preview_raw", "") or "").strip()
        s["preview"] = raw[:60] + ("..." if len(raw) > 60 else "") if raw else ""
        return s

    def session_count(self, source: str = None) -> int:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    if source:
                        cur.execute(
                            "SELECT COUNT(*) AS c FROM sessions WHERE source = %s",
                            (source,),
                        )
                    else:
                        cur.execute("SELECT COUNT(*) AS c FROM sessions")
                    return int(cur.fetchone()["c"])

    def message_count(self, session_id: str = None) -> int:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    if session_id:
                        cur.execute(
                            "SELECT COUNT(*) AS c FROM messages WHERE session_id = %s",
                            (session_id,),
                        )
                    else:
                        cur.execute("SELECT COUNT(*) AS c FROM messages")
                    return int(cur.fetchone()["c"])

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get_session(session_id)
        if not session:
            return None
        return {**session, "messages": self.get_messages(session_id)}

    def export_all(self, source: str = None) -> List[Dict[str, Any]]:
        sessions = self.search_sessions(source=source, limit=100000)
        return [
            {**s, "messages": self.get_messages(s["id"])} for s in sessions
        ]

    def clear_messages(self, session_id: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
                cur.execute(
                    "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = %s",
                    (session_id,),
                )

        self._execute_write(_do)

    def delete_session(
        self,
        session_id: str,
        sessions_dir: Optional[Path] = None,
    ) -> bool:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
                cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
                return cur.rowcount > 0

        ok = bool(self._execute_write(_do))
        if ok and sessions_dir:
            from hermes_state import SessionDB

            SessionDB._remove_session_files(sessions_dir, session_id)
        return ok

    def prune_sessions(
        self,
        older_than_days: int = 90,
        source: str = None,
        sessions_dir: Optional[Path] = None,
    ) -> int:
        cutoff = time.time() - older_than_days * 86400

        def _do(conn):
            with conn.cursor() as cur:
                if source:
                    cur.execute(
                        """
                        SELECT id FROM sessions
                        WHERE started_at < %s AND source = %s
                        """,
                        (cutoff, source),
                    )
                else:
                    cur.execute(
                        "SELECT id FROM sessions WHERE started_at < %s",
                        (cutoff,),
                    )
                ids = [r["id"] for r in cur.fetchall()]
                for sid in ids:
                    cur.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
                    cur.execute("DELETE FROM sessions WHERE id = %s", (sid,))
                return ids

        removed = self._execute_write(_do) or []
        if sessions_dir:
            from hermes_state import SessionDB

            for sid in removed:
                SessionDB._remove_session_files(sessions_dir, sid)
        return len(removed)

    def get_meta(self, key: str) -> Optional[str]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT value FROM state_meta WHERE key = %s", (key,))
                    row = cur.fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO state_meta (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (key, value),
                )

        self._execute_write(_do)

    def prune_empty_ghost_sessions(self, sessions_dir: Optional[Path] = None) -> int:
        cutoff = time.time() - 86400

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM sessions
                    WHERE source = 'tui' AND title IS NULL AND ended_at IS NOT NULL
                      AND started_at < %s
                      AND NOT EXISTS (
                          SELECT 1 FROM messages WHERE messages.session_id = sessions.id
                      )
                    """,
                    (cutoff,),
                )
                return [r["id"] for r in cur.fetchall()]

        removed_ids = self._execute_write(_do) or []
        if removed_ids:

            def _delete(conn):
                with conn.cursor() as cur:
                    for sid in removed_ids:
                        cur.execute("DELETE FROM sessions WHERE id = %s", (sid,))

            self._execute_write(_delete)
        if sessions_dir and removed_ids:
            from hermes_state import SessionDB

            for sid in removed_ids:
                SessionDB._remove_session_files(sessions_dir, sid)
        return len(removed_ids)

    def finalize_orphaned_compression_sessions(self) -> int:
        cutoff = time.time() - 604800

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions SET ended_at = %s, end_reason = 'orphaned_compression'
                    WHERE api_call_count = 0 AND end_reason IS NULL AND ended_at IS NULL
                      AND started_at < %s AND parent_session_id IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM sessions p
                          WHERE p.id = sessions.parent_session_id
                            AND p.end_reason = 'compression' AND p.ended_at IS NOT NULL
                      )
                      AND EXISTS (
                          SELECT 1 FROM messages m WHERE m.session_id = sessions.id
                      )
                    """,
                    (time.time(), cutoff),
                )
                return cur.rowcount

        return self._execute_write(_do) or 0

    def maybe_auto_prune_and_vacuum(
        self,
        retention_days: int = 90,
        min_interval_hours: int = 24,
        vacuum: bool = True,
        sessions_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"skipped": False, "pruned": 0, "vacuumed": False}
        try:
            last_raw = self.get_meta("last_auto_prune")
            now = time.time()
            if last_raw:
                try:
                    if now - float(last_raw) < min_interval_hours * 3600:
                        result["skipped"] = True
                        return result
                except (TypeError, ValueError):
                    pass
            pruned = self.prune_sessions(
                older_than_days=retention_days, sessions_dir=sessions_dir
            )
            result["pruned"] = pruned
            self.set_meta("last_auto_prune", str(now))
        except Exception as exc:
            logger.warning("postgres session auto-maintenance failed: %s", exc)
            result["error"] = str(exc)
        return result

    # ── handoff ───────────────────────────────────────────────────────

    def request_handoff(self, session_id: str, platform: str) -> bool:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions SET handoff_state = 'pending',
                        handoff_platform = %s, handoff_error = NULL
                    WHERE id = %s AND (handoff_state IS NULL
                        OR handoff_state IN ('completed', 'failed'))
                    """,
                    (platform, session_id),
                )
                return cur.rowcount > 0

        return bool(self._execute_write(_do))

    def get_handoff_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self.get_session(session_id)
        if not row or not row.get("handoff_state"):
            return None
        return {
            "state": row["handoff_state"],
            "platform": row["handoff_platform"],
            "error": row["handoff_error"],
        }

    def list_pending_handoffs(self) -> List[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM sessions WHERE handoff_state = 'pending'
                        ORDER BY started_at ASC
                        """
                    )
                    return [dict(r) for r in cur.fetchall()]

    def claim_handoff(self, session_id: str) -> bool:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions SET handoff_state = 'running'
                    WHERE id = %s AND handoff_state = 'pending'
                    """,
                    (session_id,),
                )
                return cur.rowcount > 0

        return bool(self._execute_write(_do))

    def complete_handoff(self, session_id: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions SET handoff_state = 'completed', handoff_error = NULL
                    WHERE id = %s
                    """,
                    (session_id,),
                )

        self._execute_write(_do)

    def fail_handoff(self, session_id: str, error: str) -> None:
        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions SET handoff_state = 'failed', handoff_error = %s
                    WHERE id = %s
                    """,
                    (error[:500], session_id),
                )

        self._execute_write(_do)

    # ── telegram topic mode (same semantics as SQLite) ────────────────

    def apply_telegram_topic_migration(self) -> None:
        self._init_schema()

    def enable_telegram_topic_mode(
        self, *, chat_id: str, user_id: str, enabled: bool = True
    ) -> None:
        now = time.time()

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO telegram_dm_topic_mode (chat_id, user_id, enabled, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (chat_id, user_id) DO UPDATE SET
                        enabled = EXCLUDED.enabled, updated_at = EXCLUDED.updated_at
                    """,
                    (str(chat_id), str(user_id), 1 if enabled else 0, now),
                )

        self._execute_write(_do)

    def disable_telegram_topic_mode(self, *, chat_id: str, user_id: str) -> None:
        now = time.time()

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE telegram_dm_topic_mode SET enabled = 0, updated_at = %s
                    WHERE chat_id = %s AND user_id = %s
                    """,
                    (now, str(chat_id), str(user_id)),
                )
                cur.execute(
                    "DELETE FROM telegram_dm_topic_bindings WHERE chat_id = %s",
                    (str(chat_id),),
                )

        self._execute_write(_do)

    def is_telegram_topic_mode_enabled(self, *, chat_id: str, user_id: str) -> bool:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT enabled FROM telegram_dm_topic_mode
                        WHERE chat_id = %s AND user_id = %s
                        """,
                        (str(chat_id), str(user_id)),
                    )
                    row = cur.fetchone()
        return bool(row and row["enabled"])

    def get_telegram_topic_binding(
        self, *, chat_id: str, thread_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM telegram_dm_topic_bindings WHERE chat_id = %s AND thread_id = %s",
                        (str(chat_id), str(thread_id)),
                    )
                    row = cur.fetchone()
        return dict(row) if row else None

    def bind_telegram_topic(
        self,
        *,
        chat_id: str,
        thread_id: str,
        user_id: str,
        session_key: str,
        session_id: str,
        managed_mode: str = "auto",
    ) -> None:
        now = time.time()

        def _do(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chat_id, thread_id FROM telegram_dm_topic_bindings WHERE session_id = %s",
                    (str(session_id),),
                )
                existing = cur.fetchone()
                if existing and (
                    str(existing["chat_id"]) != str(chat_id)
                    or str(existing["thread_id"]) != str(thread_id)
                ):
                    raise ValueError("session is already linked to another Telegram topic")
                cur.execute(
                    """
                    INSERT INTO telegram_dm_topic_bindings (
                        chat_id, thread_id, user_id, session_key, session_id,
                        managed_mode, linked_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (chat_id, thread_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        session_key = EXCLUDED.session_key,
                        session_id = EXCLUDED.session_id,
                        managed_mode = EXCLUDED.managed_mode,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        str(chat_id),
                        str(thread_id),
                        str(user_id),
                        str(session_key),
                        str(session_id),
                        managed_mode,
                        now,
                        now,
                    ),
                )

        self._execute_write(_do)

    def is_telegram_session_linked_to_topic(self, *, session_id: str) -> bool:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM telegram_dm_topic_bindings WHERE session_id = %s LIMIT 1",
                        (str(session_id),),
                    )
                    return cur.fetchone() is not None

    def list_telegram_topic_bindings_for_chat(
        self, *, chat_id: str
    ) -> List[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM telegram_dm_topic_bindings WHERE chat_id = %s",
                        (str(chat_id),),
                    )
                    return [dict(r) for r in cur.fetchall()]

    def get_telegram_topic_binding_by_session(
        self, *, session_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM telegram_dm_topic_bindings
                        WHERE session_id = %s LIMIT 1
                        """,
                        (str(session_id),),
                    )
                    row = cur.fetchone()
        return dict(row) if row else None

    def list_unlinked_telegram_sessions_for_user(
        self, *, chat_id: str, user_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        sql = f"""
            SELECT s.*, {_PREVIEW_SUBQ} AS _preview_raw, {_LAST_ACTIVE_SUBQ} AS last_active
            FROM sessions s
            WHERE s.source = 'telegram' AND s.user_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM telegram_dm_topic_bindings b WHERE b.session_id = s.id
              )
            ORDER BY last_active DESC, s.started_at DESC
            LIMIT %s
        """
        with self._with_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (str(user_id), int(limit)))
                    rows = cur.fetchall()
        sessions = []
        for row in rows:
            session = dict(row)
            raw = str(session.pop("_preview_raw", "") or "").strip()
            session["preview"] = raw[:60] + ("..." if len(raw) > 60 else "") if raw else ""
            sessions.append(session)
        return sessions
