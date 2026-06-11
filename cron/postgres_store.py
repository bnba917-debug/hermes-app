"""PostgreSQL storage for cron jobs — per-job rows + process cache."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from agent.session_storage.postgres_pool import holder_for
from hermes_time import now as _hermes_now

logger = logging.getLogger(__name__)

_LEGACY_DDL = """
CREATE TABLE IF NOT EXISTS hermes_cron_store (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    jobs JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TEXT NOT NULL DEFAULT ''
);
"""

_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS hermes_cron_jobs (
    id TEXT PRIMARY KEY,
    job JSONB NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hermes_cron_jobs_order
    ON hermes_cron_jobs (sort_order, id);
CREATE TABLE IF NOT EXISTS hermes_cron_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class PostgresCronStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._holder = holder_for(dsn)
        self._cache_lock = threading.Lock()
        self._cache_jobs: Optional[List[Dict[str, Any]]] = None
        self._cache_stamp: Optional[str] = None
        self._init_db()

    def _init_db(self) -> None:
        with self._holder.lock:
            conn = self._holder.connection()
            with conn.cursor() as cur:
                cur.execute(_LEGACY_DDL)
                cur.execute(_JOBS_DDL)
                cur.execute(
                    """
                    INSERT INTO hermes_cron_meta (key, value) VALUES ('schema', '2')
                    ON CONFLICT (key) DO NOTHING
                    """
                )
            conn.commit()
            self._migrate_legacy_blob(conn)

    def _migrate_legacy_blob(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM hermes_cron_jobs")
            if int(cur.fetchone()["c"]) > 0:
                return
            cur.execute("SELECT jobs FROM hermes_cron_store WHERE id = 1")
            row = cur.fetchone()
            if not row or not row["jobs"]:
                return
            jobs = row["jobs"]
            if isinstance(jobs, str):
                jobs = json.loads(jobs)
            for i, job in enumerate(jobs or []):
                jid = str(job.get("id") or f"legacy-{i}")
                cur.execute(
                    """
                    INSERT INTO hermes_cron_jobs (id, job, sort_order)
                    VALUES (%s, %s::jsonb, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (jid, json.dumps(job, ensure_ascii=False), i),
                )
            cur.execute(
                """
                INSERT INTO hermes_cron_meta (key, value) VALUES ('updated_at', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (_hermes_now().isoformat(),),
            )
        conn.commit()
        logger.info("Migrated cron jobs from hermes_cron_store blob to hermes_cron_jobs")

    def _read_stamp(self, conn) -> str:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM hermes_cron_meta WHERE key = 'updated_at'"
            )
            row = cur.fetchone()
        return str(row["value"]) if row else ""

    def _write_stamp(self, conn) -> str:
        stamp = _hermes_now().isoformat()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hermes_cron_meta (key, value) VALUES ('updated_at', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (stamp,),
            )
        return stamp

    def load_jobs(self) -> List[Dict[str, Any]]:
        with self._cache_lock:
            if self._cache_jobs is not None:
                return list(self._cache_jobs)

        with self._holder.lock:
            conn = self._holder.connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT job FROM hermes_cron_jobs ORDER BY sort_order, id"
                )
                rows = cur.fetchall()
        jobs = [dict(r["job"]) for r in rows]
        with self._cache_lock:
            self._cache_jobs = jobs
            self._cache_stamp = self._read_stamp(conn)
        return list(jobs)

    def save_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        with self._holder.lock:
            conn = self._holder.connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM hermes_cron_jobs")
                    for i, job in enumerate(jobs):
                        jid = str(job.get("id") or f"job-{i}")
                        cur.execute(
                            """
                            INSERT INTO hermes_cron_jobs (id, job, sort_order)
                            VALUES (%s, %s::jsonb, %s)
                            """,
                            (jid, json.dumps(job, ensure_ascii=False), i),
                        )
                    # Keep legacy singleton in sync for older tools.
                    cur.execute(
                        """
                        INSERT INTO hermes_cron_store (id, jobs, updated_at)
                        VALUES (1, %s::jsonb, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            jobs = EXCLUDED.jobs,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            json.dumps(jobs, ensure_ascii=False),
                            _hermes_now().isoformat(),
                        ),
                    )
                stamp = self._write_stamp(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        with self._cache_lock:
            self._cache_jobs = list(jobs)
            self._cache_stamp = stamp


_store: Optional[PostgresCronStore] = None
_store_lock = threading.Lock()


def get_postgres_cron_store(dsn: str) -> PostgresCronStore:
    global _store
    with _store_lock:
        if _store is None or _store._dsn != dsn:
            _store = PostgresCronStore(dsn)
        return _store
