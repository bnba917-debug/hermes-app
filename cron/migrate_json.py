"""Migrate ``jobs.json`` into PostgreSQL ``hermes_cron_store``."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from cron.jobs import JOBS_FILE
from cron.postgres_store import PostgresCronStore

logger = logging.getLogger(__name__)


@dataclass
class CronMigrationStats:
    jobs: int = 0


def migrate_cron_jobs_json(
    dsn: str,
    jobs_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> CronMigrationStats:
    path = jobs_path or JOBS_FILE
    stats = CronMigrationStats()
    if not path.is_file():
        return stats

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    jobs = data.get("jobs") or []
    stats.jobs = len(jobs)

    if dry_run or not jobs:
        return stats

    store = PostgresCronStore(dsn)
    store.save_jobs(jobs)
    logger.info("Migrated %d cron jobs from %s to PostgreSQL", stats.jobs, path)
    return stats
