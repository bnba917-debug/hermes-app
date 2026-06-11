"""App user + SMS OTP registry in PostgreSQL."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from plugins.app_gateway.user_registry import AppUserRecord, _record_from_mapping

logger = logging.getLogger(__name__)

_USERS_DDL = """
CREATE TABLE IF NOT EXISTS hermes_app_users (
    user_id TEXT PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    created_at DOUBLE PRECISION NOT NULL,
    initialized_at DOUBLE PRECISION,
    last_login_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_hermes_app_users_phone ON hermes_app_users (phone);
"""

_OTP_DDL = """
CREATE TABLE IF NOT EXISTS hermes_app_sms_otp (
    phone TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
"""


class PostgresUserRegistry:
    """Phone registration store backed by shared ``postgres_url``."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL user registry requires psycopg. "
                "Install: pip install 'psycopg[binary]'"
            ) from exc
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_USERS_DDL)
                    cur.execute(_OTP_DDL)
                conn.commit()

    def get_by_phone(self, phone: str) -> Optional[AppUserRecord]:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM hermes_app_users WHERE phone = %s",
                        (phone,),
                    )
                    row = cur.fetchone()
                    return _record_from_mapping(row) if row else None

    def get_by_user_id(self, user_id: str) -> Optional[AppUserRecord]:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM hermes_app_users WHERE user_id = %s",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    return _record_from_mapping(row) if row else None

    def upsert_user(self, user_id: str, phone: str) -> AppUserRecord:
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM hermes_app_users WHERE phone = %s",
                        (phone,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE hermes_app_users
                            SET last_login_at = %s
                            WHERE phone = %s
                            """,
                            (now, phone),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO hermes_app_users
                                (user_id, phone, created_at, last_login_at)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (user_id, phone, now, now),
                        )
                    cur.execute(
                        "SELECT * FROM hermes_app_users WHERE phone = %s",
                        (phone,),
                    )
                    row = cur.fetchone()
                conn.commit()
                return _record_from_mapping(row)

    def mark_initialized(self, user_id: str) -> None:
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE hermes_app_users
                        SET initialized_at = %s
                        WHERE user_id = %s
                        """,
                        (now, user_id),
                    )
                conn.commit()

    def store_otp(self, phone: str, code: str, *, ttl_seconds: int = 300) -> None:
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hermes_app_sms_otp
                            (phone, code, expires_at, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (phone) DO UPDATE SET
                            code = EXCLUDED.code,
                            expires_at = EXCLUDED.expires_at,
                            created_at = EXCLUDED.created_at
                        """,
                        (phone, code, now + ttl_seconds, now),
                    )
                conn.commit()

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT phone FROM hermes_app_users WHERE user_id = %s",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    phone = str(row["phone"]) if row else ""
                    cur.execute(
                        "DELETE FROM hermes_app_users WHERE user_id = %s",
                        (user_id,),
                    )
                    deleted = cur.rowcount > 0
                    if phone:
                        cur.execute(
                            "DELETE FROM hermes_app_sms_otp WHERE phone = %s",
                            (phone,),
                        )
                conn.commit()
                return deleted

    def verify_otp(self, phone: str, code: str) -> bool:
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT code, expires_at FROM hermes_app_sms_otp
                        WHERE phone = %s
                        """,
                        (phone,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return False
                    stored_code = row["code"]
                    expires_at = float(row["expires_at"])
                    if now > expires_at:
                        cur.execute(
                            "DELETE FROM hermes_app_sms_otp WHERE phone = %s",
                            (phone,),
                        )
                        conn.commit()
                        return False
                    ok = str(stored_code) == str(code).strip()
                    if ok:
                        cur.execute(
                            "DELETE FROM hermes_app_sms_otp WHERE phone = %s",
                            (phone,),
                        )
                    conn.commit()
                    return ok
