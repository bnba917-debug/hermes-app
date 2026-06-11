#!/usr/bin/env python3
"""Wipe Hermes storage (PostgreSQL + local SQLite/files) after benchmarks or dev resets.

Usage:
  python scripts/wipe_hermes_storage.py --dry-run
  python scripts/wipe_hermes_storage.py --confirm wipe-all

Requires ``--confirm wipe-all`` to mutate data.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _postgres_tables(dsn: str) -> list[str]:
    import psycopg

    static = [
        "messages",
        "sessions",
        "telegram_dm_topic_bindings",
        "telegram_dm_topic_mode",
        "state_meta",
        "schema_version",
        "hermes_audit_events",
        "hermes_app_memory_entries",
        "hermes_cron_jobs",
        "hermes_cron_store",
        "hermes_cron_meta",
        "hermes_app_sms_otp",
        "hermes_app_users",
    ]
    kanban_schemas: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name LIKE 'kanban_%'
                """
            )
            kanban_schemas = [row[0] for row in cur.fetchall()]
    return static, kanban_schemas


def wipe_postgres(dsn: str, *, dry_run: bool) -> dict:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg required: uv pip install -e '.[postgres]'") from exc

    static, kanban_schemas = _postgres_tables(dsn)
    actions: list[str] = []

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            for schema in kanban_schemas:
                sql = f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'
                actions.append(sql)
                if not dry_run:
                    cur.execute(sql)
            if static:
                joined = ", ".join(static)
                sql = f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"
                actions.append(sql)
                if not dry_run:
                    cur.execute(sql)

    return {"backend": "postgres", "kanban_schemas_dropped": kanban_schemas, "tables_truncated": static, "dry_run": dry_run}


def wipe_sqlite_files(home: Path, *, dry_run: bool) -> list[str]:
    removed: list[str] = []
    candidates = [
        home / "state.db",
        home / "state.db-wal",
        home / "state.db-shm",
        home / "kanban.db",
        home / "app_gateway" / "audit.db",
        home / "app_gateway" / "vector_memory.db",
        home / "app_gateway" / "users_registry.db",
        home / "cron" / "jobs.json",
    ]
    errors: list[str] = []
    for path in candidates:
        if path.is_file():
            removed.append(str(path))
            if not dry_run:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    errors.append(f"{path}: {exc}")
    users_root = home / "app_gateway" / "users"
    if users_root.is_dir():
        for child in users_root.iterdir():
            if child.is_dir():
                removed.append(str(child))
                if not dry_run:
                    try:
                        shutil.rmtree(child, ignore_errors=True)
                    except OSError as exc:
                        errors.append(f"{child}: {exc}")
    if errors:
        removed.append(f"errors:{len(errors)}")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Wipe Hermes DB + app_gateway user trees")
    parser.add_argument(
        "--confirm",
        default="",
        help='Must be exactly "wipe-all" to execute',
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-url", default="", help="Override DSN")
    parser.add_argument("--hermes-home", default="", help="Override HERMES_HOME path")
    args = parser.parse_args()

    if args.confirm != "wipe-all" and not args.dry_run:
        print('Refusing to wipe without --confirm wipe-all (or use --dry-run)', file=sys.stderr)
        return 2

    if args.hermes_home:
        os.environ["HERMES_HOME"] = str(Path(args.hermes_home).expanduser().resolve())

    from hermes_constants import get_hermes_home
    from agent.session_storage.config import resolve_postgres_url, resolve_session_backend

    home = get_hermes_home()
    dsn = (args.postgres_url or "").strip() or resolve_postgres_url()
    backend, resolved_dsn = resolve_session_backend()

    print(f"HERMES_HOME: {home}")
    print(f"session_backend: {backend}")

    report: dict = {"sqlite_files": wipe_sqlite_files(home, dry_run=args.dry_run)}

    pg_dsn = (args.postgres_url or "").strip() or dsn or resolved_dsn
    if pg_dsn:
        try:
            report["postgres"] = wipe_postgres(pg_dsn, dry_run=args.dry_run)
        except Exception as exc:
            report["postgres_error"] = str(exc)
            print(f"PostgreSQL wipe failed: {exc}", file=sys.stderr)
            if not args.dry_run:
                return 1

    import json

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("(dry-run — no data deleted)")
    else:
        print("Storage wiped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
