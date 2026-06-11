#!/usr/bin/env python3
"""Remove deprecated user-skills trees and private skill rows from PostgreSQL."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _default_dsn() -> str:
    from plugins.app_gateway.config import load_app_gateway_config

    return str(load_app_gateway_config().postgres_url or "").strip()


def _default_home() -> Path:
    from plugins.app_gateway.user_scope import operator_app_gateway_root

    return operator_app_gateway_root()


def _counts(cur) -> dict[str, int]:
    out: dict[str, int] = {}
    queries = {
        "private_skills": "SELECT COUNT(*) FROM hermes_app_skills WHERE visibility = 'private'",
        "private_skill_files": """
            SELECT COUNT(*) FROM hermes_app_skill_files f
            JOIN hermes_app_skills s ON s.id = f.skill_id
            WHERE s.visibility = 'private'
        """,
        "public_skills": "SELECT COUNT(*) FROM hermes_app_skills WHERE visibility = 'public'",
    }
    for key, sql in queries.items():
        cur.execute(sql)
        out[key] = int(cur.fetchone()[0])
    return out


def cleanup_postgres(dsn: str, *, dry_run: bool) -> dict:
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            before = _counts(cur)
            if dry_run:
                conn.rollback()
                return {"before": before, "deleted_skill_files": before["private_skill_files"], "deleted_skills": before["private_skills"], "dry_run": True}
            cur.execute(
                """
                DELETE FROM hermes_app_skill_files f
                USING hermes_app_skills s
                WHERE f.skill_id = s.id AND s.visibility = 'private'
                """
            )
            deleted_files = cur.rowcount
            cur.execute("DELETE FROM hermes_app_skills WHERE visibility = 'private'")
            deleted_skills = cur.rowcount
            after = _counts(cur)
        conn.commit()
    return {
        "before": before,
        "after": after,
        "deleted_skill_files": deleted_files,
        "deleted_skills": deleted_skills,
        "dry_run": False,
    }


def cleanup_user_skills_dir(home: Path, *, dry_run: bool) -> dict:
    target = home / "user-skills"
    if not target.exists():
        return {"path": str(target), "existed": False, "removed": False, "dry_run": dry_run}
    child_dirs = sum(1 for p in target.rglob("*") if p.is_dir())
    child_files = sum(1 for p in target.rglob("*") if p.is_file())
    if not dry_run:
        shutil.rmtree(target, ignore_errors=True)
    return {
        "path": str(target),
        "existed": True,
        "child_dirs": child_dirs,
        "child_files": child_files,
        "removed": not dry_run,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup deprecated app_gateway user-skills storage")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not delete")
    parser.add_argument("--postgres-url", default="", help="Override PostgreSQL DSN")
    parser.add_argument("--hermes-home", default="", help="Override operator Hermes home")
    args = parser.parse_args()

    dsn = (args.postgres_url or _default_dsn()).strip()
    home = Path(args.hermes_home).expanduser() if args.hermes_home else _default_home()
    dry_run = bool(args.dry_run)

    print(f"operator_home={home}")
    print(f"postgres={'set' if dsn else 'missing'}")
    print(f"mode={'dry-run' if dry_run else 'delete'}")

    dir_result = cleanup_user_skills_dir(home, dry_run=dry_run)
    print("user-skills:", dir_result)

    if not dsn:
        print("skip postgres: no DSN")
        return 0

    try:
        pg_result = cleanup_postgres(dsn, dry_run=dry_run)
    except Exception as exc:
        print(f"postgres cleanup failed: {exc}")
        return 1
    print("postgres:", pg_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
