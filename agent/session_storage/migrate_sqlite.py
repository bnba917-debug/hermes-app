"""Bulk migration from SQLite ``state.db`` to PostgreSQL session tables."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SESSION_COLUMNS = (
    "id",
    "source",
    "user_id",
    "model",
    "model_config",
    "system_prompt",
    "parent_session_id",
    "started_at",
    "ended_at",
    "end_reason",
    "message_count",
    "tool_call_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "billing_provider",
    "billing_base_url",
    "billing_mode",
    "estimated_cost_usd",
    "actual_cost_usd",
    "cost_status",
    "cost_source",
    "pricing_version",
    "title",
    "api_call_count",
    "handoff_state",
    "handoff_platform",
    "handoff_error",
)

MESSAGE_COLUMNS = (
    "id",
    "session_id",
    "role",
    "content",
    "tool_call_id",
    "tool_calls",
    "tool_name",
    "timestamp",
    "token_count",
    "finish_reason",
    "reasoning",
    "reasoning_content",
    "reasoning_details",
    "codex_reasoning_items",
    "codex_message_items",
)


@dataclass
class MigrationStats:
    sessions: int = 0
    messages: int = 0
    meta: int = 0
    telegram_mode: int = 0
    telegram_bindings: int = 0
    sessions_skipped: int = 0
    messages_skipped: int = 0
    errors: List[str] = field(default_factory=list)


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _sqlite_rows(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT * FROM {table}")
    return [dict(r) for r in cur.fetchall()]


def _session_tuple(row: Dict[str, Any]) -> tuple:
    return tuple(row.get(c) for c in SESSION_COLUMNS)


def _message_tuple(row: Dict[str, Any]) -> tuple:
    return tuple(row.get(c) for c in MESSAGE_COLUMNS)


def _session_insert_order(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order session rows so ``parent_session_id`` FK targets exist first."""
    by_id = {r["id"]: r for r in rows}
    inserted: set[str] = set()
    ordered: List[Dict[str, Any]] = []
    remaining = list(rows)
    for _ in range(len(rows) + 1):
        if not remaining:
            break
        next_remaining: List[Dict[str, Any]] = []
        progress = False
        for row in remaining:
            pid = row.get("parent_session_id")
            if not pid or pid in inserted or pid not in by_id:
                ordered.append(row)
                inserted.add(row["id"])
                progress = True
            else:
                next_remaining.append(row)
        if not progress:
            ordered.extend(next_remaining)
            break
        remaining = next_remaining
    return ordered


def migrate_state_db(
    sqlite_path: Path,
    dsn: str,
    *,
    merge: bool = True,
    batch_size: int = 500,
    dry_run: bool = False,
) -> MigrationStats:
    """Copy ``state.db`` into PostgreSQL, preserving session and message IDs."""
    stats = MigrationStats()
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    src = sqlite3.connect(str(sqlite_path))
    try:
        sessions = _sqlite_rows(src, "sessions")
        messages = _sqlite_rows(src, "messages")
        meta = _sqlite_rows(src, "state_meta") if _sqlite_table_exists(src, "state_meta") else []
        topic_mode = (
            _sqlite_rows(src, "telegram_dm_topic_mode")
            if _sqlite_table_exists(src, "telegram_dm_topic_mode")
            else []
        )
        topic_bindings = (
            _sqlite_rows(src, "telegram_dm_topic_bindings")
            if _sqlite_table_exists(src, "telegram_dm_topic_bindings")
            else []
        )
    finally:
        src.close()

    stats.sessions = len(sessions)
    stats.messages = len(messages)
    stats.meta = len(meta)
    stats.telegram_mode = len(topic_mode)
    stats.telegram_bindings = len(topic_bindings)

    if dry_run:
        return stats

    sessions = _session_insert_order(sessions)

    from agent.session_storage.postgres_session_db import PostgresSessionDB

    pg = PostgresSessionDB(dsn)

    sess_cols = ", ".join(SESSION_COLUMNS)
    sess_placeholders = ", ".join("%s" for _ in SESSION_COLUMNS)
    if merge:
        sess_conflict = (
            f"ON CONFLICT (id) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in SESSION_COLUMNS if c != "id")
        )
    else:
        sess_conflict = "ON CONFLICT (id) DO NOTHING"

    msg_cols = ", ".join(MESSAGE_COLUMNS)
    msg_placeholders = ", ".join("%s" for _ in MESSAGE_COLUMNS)
    msg_conflict = "ON CONFLICT (id) DO NOTHING"

    with pg._lock:
        with pg._connect() as conn:
            with conn.cursor() as cur:
                if not merge:
                    cur.execute(
                        "TRUNCATE telegram_dm_topic_bindings, telegram_dm_topic_mode, "
                        "messages, sessions, state_meta RESTART IDENTITY CASCADE"
                    )

                for i in range(0, len(sessions), batch_size):
                    batch = sessions[i : i + batch_size]
                    cur.executemany(
                        f"INSERT INTO sessions ({sess_cols}) VALUES ({sess_placeholders}) "
                        f"{sess_conflict}",
                        [_session_tuple(r) for r in batch],
                    )

                max_msg_id = 0
                for i in range(0, len(messages), batch_size):
                    batch = messages[i : i + batch_size]
                    cur.executemany(
                        f"INSERT INTO messages ({msg_cols}) VALUES ({msg_placeholders}) "
                        f"{msg_conflict}",
                        [_message_tuple(r) for r in batch],
                    )
                    for r in batch:
                        mid = r.get("id")
                        if mid is not None:
                            max_msg_id = max(max_msg_id, int(mid))

                if max_msg_id > 0:
                    cur.execute(
                        "SELECT setval(pg_get_serial_sequence('messages', 'id'), %s, true)",
                        (max_msg_id,),
                    )

                for row in meta:
                    cur.execute(
                        """
                        INSERT INTO state_meta (key, value) VALUES (%s, %s)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                        """,
                        (row["key"], row["value"]),
                    )

                for row in topic_mode:
                    cur.execute(
                        """
                        INSERT INTO telegram_dm_topic_mode (chat_id, user_id, enabled, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (chat_id, user_id) DO UPDATE SET
                            enabled = EXCLUDED.enabled,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            row["chat_id"],
                            row["user_id"],
                            row.get("enabled", 0),
                            row.get("updated_at"),
                        ),
                    )

                for row in topic_bindings:
                    cur.execute(
                        """
                        INSERT INTO telegram_dm_topic_bindings (
                            chat_id, thread_id, user_id, session_key, session_id,
                            managed_mode, linked_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (chat_id, thread_id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            session_key = EXCLUDED.session_key,
                            session_id = EXCLUDED.session_id,
                            managed_mode = EXCLUDED.managed_mode,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            row["chat_id"],
                            row["thread_id"],
                            row["user_id"],
                            row["session_key"],
                            row["session_id"],
                            row.get("managed_mode", "auto"),
                            row.get("linked_at"),
                            row.get("updated_at"),
                        ),
                    )

                cur.execute("DELETE FROM schema_version")
                from agent.session_storage.postgres_session_db import SCHEMA_VERSION

                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s)",
                    (SCHEMA_VERSION,),
                )

            conn.commit()

    logger.info(
        "Migrated %d sessions, %d messages, %d meta, %d telegram mode, %d bindings",
        stats.sessions,
        stats.messages,
        stats.meta,
        stats.telegram_mode,
        stats.telegram_bindings,
    )
    return stats


@dataclass
class AppGatewayMigrationStats:
    audit_events: int = 0
    memory_entries: int = 0


def migrate_app_gateway_sqlite(
    dsn: str,
    *,
    hermes_home: Optional[Path] = None,
    dry_run: bool = False,
    skip_if_pg_has_rows: bool = True,
) -> AppGatewayMigrationStats:
    """Migrate ``app_gateway/audit.db`` and ``vector_memory.db`` into PostgreSQL."""
    from hermes_constants import get_hermes_home

    home = hermes_home or get_hermes_home()
    audit_path = home / "app_gateway" / "audit.db"
    vector_path = home / "app_gateway" / "vector_memory.db"
    stats = AppGatewayMigrationStats()

    if audit_path.is_file():
        conn = sqlite3.connect(str(audit_path))
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM audit_events").fetchall()]
        conn.close()
        stats.audit_events = len(rows)
        if not dry_run and rows:
            import psycopg
            from psycopg.rows import dict_row

            from plugins.app_gateway.audit_backends import PostgresAuditBackend

            PostgresAuditBackend(dsn)
            with psycopg.connect(dsn, row_factory=dict_row) as pg:
                with pg.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS c FROM hermes_audit_events")
                    existing = int(cur.fetchone()["c"])
                    if skip_if_pg_has_rows and existing > 0:
                        logger.info(
                            "Skipping audit migration (%d rows already in PostgreSQL)",
                            existing,
                        )
                    else:
                        for row in rows:
                            payload = row.get("payload")
                            if isinstance(payload, str):
                                payload_json = payload
                            else:
                                payload_json = json.dumps(
                                    payload or {}, ensure_ascii=False
                                )
                            cur.execute(
                                """
                                INSERT INTO hermes_audit_events
                                    (ts, user_id, session_id, device_id, event_type, payload)
                                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                                """,
                                (
                                    row["ts"],
                                    row["user_id"],
                                    row["session_id"],
                                    row.get("device_id"),
                                    row["event_type"],
                                    payload_json,
                                ),
                            )
                pg.commit()

    if vector_path.is_file():
        conn = sqlite3.connect(str(vector_path))
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM memory_entries").fetchall()]
        conn.close()
        stats.memory_entries = len(rows)
        if not dry_run and rows:
            import psycopg
            from psycopg.rows import dict_row

            from plugins.app_gateway.postgres_vector_memory import PostgresUserVectorMemory

            PostgresUserVectorMemory(dsn)
            with psycopg.connect(dsn, row_factory=dict_row) as pg:
                with pg.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS c FROM hermes_app_memory_entries")
                    existing = int(cur.fetchone()["c"])
                    if skip_if_pg_has_rows and existing > 0:
                        logger.info(
                            "Skipping vector memory migration (%d rows already in PostgreSQL)",
                            existing,
                        )
                    else:
                        for row in rows:
                            cur.execute(
                                """
                                INSERT INTO hermes_app_memory_entries
                                    (user_id, session_id, body, created_at)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (
                                    row["user_id"],
                                    row["session_id"],
                                    row["body"],
                                    row["created_at"],
                                ),
                            )
                pg.commit()

    return stats
