"""Migrate Kanban SQLite boards into PostgreSQL schemas."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from agent.kanban_storage.postgres_conn import postgres_connect
from agent.kanban_storage.postgres_schema import pg_schema_name

logger = logging.getLogger(__name__)

TABLES = (
    "tasks",
    "task_links",
    "task_comments",
    "task_events",
    "task_runs",
    "kanban_notify_subs",
)


@dataclass
class KanbanBoardMigrationStats:
    board: str
    tables: Dict[str, int] = field(default_factory=dict)


def iter_kanban_sqlite_files() -> Iterator[Tuple[str, Path]]:
    from hermes_cli import kanban_db as kb

    root = kb.kanban_home()
    default_db = root / "kanban.db"
    if default_db.is_file():
        yield "default", default_db
    boards_dir = kb.boards_root()
    if boards_dir.is_dir():
        for child in sorted(boards_dir.iterdir()):
            if not child.is_dir():
                continue
            db_file = child / "kanban.db"
            if db_file.is_file():
                yield child.name, db_file


def _copy_table(
    src: sqlite3.Connection,
    dest_conn,
    schema: str,
    table: str,
) -> int:
    src.row_factory = sqlite3.Row
    rows = [dict(r) for r in src.execute(f"SELECT * FROM {table}").fetchall()]
    if not rows:
        return 0
    cols = list(rows[0].keys())
    col_sql = ", ".join(cols)
    placeholders = ", ".join("%s" for _ in cols)

    with dest_conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        for row in rows:
            vals = tuple(row[c] for c in cols)
            if table == "task_links":
                cur.execute(
                    f"""
                    INSERT INTO task_links ({col_sql}) VALUES ({placeholders})
                    ON CONFLICT (parent_id, child_id) DO NOTHING
                    """,
                    vals,
                )
            elif table == "kanban_notify_subs":
                cur.execute(
                    f"""
                    INSERT INTO kanban_notify_subs ({col_sql}) VALUES ({placeholders})
                    ON CONFLICT (task_id, platform, chat_id, thread_id) DO NOTHING
                    """,
                    vals,
                )
            elif table == "tasks":
                cur.execute(
                    f"""
                    INSERT INTO tasks ({col_sql}) VALUES ({placeholders})
                    ON CONFLICT (id) DO NOTHING
                    """,
                    vals,
                )
            elif table in ("task_comments", "task_events", "task_runs"):
                cur.execute(
                    f"""
                    INSERT INTO {table} ({col_sql}) VALUES ({placeholders})
                    ON CONFLICT (id) DO NOTHING
                    """,
                    vals,
                )
            else:
                cur.execute(
                    f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
                    vals,
                )
    return len(rows)


def _reset_serial(dest_conn, schema: str, table: str) -> None:
    if table not in ("task_comments", "task_events", "task_runs"):
        return
    with dest_conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        # Table name is from a fixed allowlist — safe to interpolate.
        cur.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table}), 1),
                true
            )
            """
        )


def migrate_board(
    sqlite_path: Path,
    dsn: str,
    board_slug: str,
    *,
    dry_run: bool = False,
) -> KanbanBoardMigrationStats:
    stats = KanbanBoardMigrationStats(board=board_slug)
    if dry_run:
        src = sqlite3.connect(str(sqlite_path))
        try:
            for table in TABLES:
                try:
                    n = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    stats.tables[table] = int(n)
                except sqlite3.OperationalError:
                    stats.tables[table] = 0
        finally:
            src.close()
        return stats

    postgres_connect(dsn, board=board_slug)
    schema = pg_schema_name(board_slug)

    import psycopg

    src = sqlite3.connect(str(sqlite_path))
    try:
        with psycopg.connect(dsn) as dest:
            with dest.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            dest.commit()
            for table in TABLES:
                try:
                    stats.tables[table] = _copy_table(src, dest, schema, table)
                except sqlite3.OperationalError:
                    stats.tables[table] = 0
            for serial_table in ("task_comments", "task_events", "task_runs"):
                if stats.tables.get(serial_table):
                    _reset_serial(dest, schema, serial_table)
            dest.commit()
    finally:
        src.close()

    logger.info("Migrated kanban board %s from %s: %s", board_slug, sqlite_path, stats.tables)
    return stats


def migrate_all_kanban_boards(dsn: str, *, dry_run: bool = False) -> List[KanbanBoardMigrationStats]:
    results = []
    for slug, path in iter_kanban_sqlite_files():
        results.append(migrate_board(path, dsn, slug, dry_run=dry_run))
    return results
