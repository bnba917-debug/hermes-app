#!/usr/bin/env python3
"""Migrate Hermes SQLite stores to PostgreSQL (sessions + app_gateway).

Migrates:
  - ``~/.hermes/state.db`` → ``sessions`` / ``messages`` / ``state_meta`` / telegram tables
  - ``~/.hermes/app_gateway/audit.db`` → ``hermes_audit_events``
  - ``~/.hermes/app_gateway/vector_memory.db`` → ``hermes_app_memory_entries``
  - ``~/.hermes/kanban.db`` and ``~/.hermes/kanban/boards/*/kanban.db`` → ``kanban_<slug>`` schemas
  - ``~/.hermes/cron/jobs.json`` → ``hermes_cron_store``

Preserves session IDs and message IDs. After success, set in ``config.yaml``::

    storage:
      session_backend: auto   # or postgres
      postgres_url: postgresql://...

Usage::

    python scripts/migrate_hermes_to_postgres.py --dry-run
    python scripts/migrate_hermes_to_postgres.py
    python scripts/migrate_hermes_to_postgres.py --only state
    python scripts/migrate_hermes_to_postgres.py --replace-state
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load_dsn() -> str:
    from agent.session_storage.config import resolve_postgres_url

    dsn = resolve_postgres_url()
    if not dsn:
        print(
            "No postgres_url found. Set storage.postgres_url or app_gateway.postgres_url "
            "in ~/.hermes/config.yaml (or HERMES_STORAGE_POSTGRES_URL).",
            file=sys.stderr,
        )
        sys.exit(1)
    return dsn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=None,
        help="Path to state.db (default: HERMES_HOME/state.db)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows only")
    parser.add_argument(
        "--only",
        choices=("all", "state", "app_gateway", "kanban", "cron"),
        default="all",
        help="Which stores to migrate (default: all)",
    )
    parser.add_argument(
        "--replace-state",
        action="store_true",
        help="TRUNCATE PostgreSQL session tables before import (destructive)",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    dsn = _load_dsn()

    if args.sqlite:
        state_path = args.sqlite
    else:
        from hermes_constants import get_hermes_home

        state_path = get_hermes_home() / "state.db"

    if args.only in ("all", "state"):
        from agent.session_storage.migrate_sqlite import migrate_state_db

        print(f"=== state.db → PostgreSQL ({state_path}) ===")
        try:
            st = migrate_state_db(
                state_path,
                dsn,
                merge=not args.replace_state,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            print(
                f"  sessions={st.sessions} messages={st.messages} meta={st.meta} "
                f"telegram_mode={st.telegram_mode} bindings={st.telegram_bindings}"
            )
        except FileNotFoundError as exc:
            print(f"  skip: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            raise

    if args.only in ("all", "app_gateway"):
        from agent.session_storage.migrate_sqlite import migrate_app_gateway_sqlite

        print("=== app_gateway SQLite → PostgreSQL ===")
        ag = migrate_app_gateway_sqlite(dsn, dry_run=args.dry_run)
        print(f"  audit_events={ag.audit_events} memory_entries={ag.memory_entries}")

    if args.only in ("all", "kanban"):
        from agent.kanban_storage.migrate_sqlite import migrate_all_kanban_boards

        print("=== Kanban SQLite boards → PostgreSQL ===")
        boards = migrate_all_kanban_boards(dsn, dry_run=args.dry_run)
        if not boards:
            print("  (no kanban.db files found)")
        for b in boards:
            print(f"  board={b.board} rows={b.tables}")

    if args.only in ("all", "cron"):
        from cron.migrate_json import migrate_cron_jobs_json

        print("=== cron/jobs.json → PostgreSQL ===")
        cr = migrate_cron_jobs_json(dsn, dry_run=args.dry_run)
        print(f"  jobs={cr.jobs}")

    if args.dry_run:
        print("\nDry run complete — no writes.")
    else:
        print(
            "\nDone. Restart gateway/CLI/cron. Suggested config:\n"
            "  storage.session_backend: auto\n"
            "  storage.kanban_backend: auto\n"
            "  storage.cron_backend: auto\n"
            "  storage.postgres_url: <your-dsn>"
        )


if __name__ == "__main__":
    main()
