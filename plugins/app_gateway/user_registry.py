"""App users keyed by phone number (SQLite or PostgreSQL via factory)."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from plugins.app_gateway.user_scope import operator_app_gateway_root


@dataclass(frozen=True)
class AppUserRecord:
    user_id: str
    phone: str
    created_at: float
    initialized_at: Optional[float]
    last_login_at: Optional[float]


def _record_from_mapping(row: Mapping[str, Any]) -> AppUserRecord:
    init = row.get("initialized_at")
    login = row.get("last_login_at")
    return AppUserRecord(
        user_id=str(row["user_id"]),
        phone=str(row["phone"]),
        created_at=float(row["created_at"]),
        initialized_at=float(init) if init is not None else None,
        last_login_at=float(login) if login is not None else None,
    )


def _row_to_record(row: sqlite3.Row) -> AppUserRecord:
    init = row["initialized_at"]
    login = row["last_login_at"]
    return AppUserRecord(
        user_id=str(row["user_id"]),
        phone=str(row["phone"]),
        created_at=float(row["created_at"]),
        initialized_at=float(init) if init is not None else None,
        last_login_at=float(login) if login is not None else None,
    )


class SqliteUserRegistry:
    """Legacy file-backed registry at ``app_gateway/users_registry.db``."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or (operator_app_gateway_root() / "users_registry.db")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_users (
                        user_id TEXT PRIMARY KEY,
                        phone TEXT NOT NULL UNIQUE,
                        created_at REAL NOT NULL,
                        initialized_at REAL,
                        last_login_at REAL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sms_otp (
                        phone TEXT PRIMARY KEY,
                        code TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
            finally:
                conn.close()

    def get_by_phone(self, phone: str) -> Optional[AppUserRecord]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM app_users WHERE phone = ?", (phone,)
                ).fetchone()
                return _row_to_record(row) if row else None
            finally:
                conn.close()

    def get_by_user_id(self, user_id: str) -> Optional[AppUserRecord]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM app_users WHERE user_id = ?", (user_id,)
                ).fetchone()
                return _row_to_record(row) if row else None
            finally:
                conn.close()

    def upsert_user(self, user_id: str, phone: str) -> AppUserRecord:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT * FROM app_users WHERE phone = ?", (phone,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE app_users SET last_login_at = ? WHERE phone = ?",
                        (now, phone),
                    )
                    row = conn.execute(
                        "SELECT * FROM app_users WHERE phone = ?", (phone,)
                    ).fetchone()
                    return _row_to_record(row)

                conn.execute(
                    """
                    INSERT INTO app_users (user_id, phone, created_at, last_login_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, phone, now, now),
                )
                row = conn.execute(
                    "SELECT * FROM app_users WHERE user_id = ?", (user_id,)
                ).fetchone()
                return _row_to_record(row)
            finally:
                conn.close()

    def mark_initialized(self, user_id: str) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE app_users SET initialized_at = ? WHERE user_id = ?",
                    (now, user_id),
                )
            finally:
                conn.close()

    def store_otp(self, phone: str, code: str, *, ttl_seconds: int = 300) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO sms_otp (phone, code, expires_at, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(phone) DO UPDATE SET
                        code = excluded.code,
                        expires_at = excluded.expires_at,
                        created_at = excluded.created_at
                    """,
                    (phone, code, now + ttl_seconds, now),
                )
            finally:
                conn.close()

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT phone FROM app_users WHERE user_id = ?", (user_id,)
                ).fetchone()
                phone = str(row["phone"]) if row else ""
                cur = conn.execute(
                    "DELETE FROM app_users WHERE user_id = ?", (user_id,)
                )
                deleted = cur.rowcount > 0
                if phone:
                    conn.execute("DELETE FROM sms_otp WHERE phone = ?", (phone,))
                return deleted
            finally:
                conn.close()

    def verify_otp(self, phone: str, code: str) -> bool:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT code, expires_at FROM sms_otp WHERE phone = ?", (phone,)
                ).fetchone()
                if not row:
                    return False
                if now > float(row["expires_at"]):
                    conn.execute("DELETE FROM sms_otp WHERE phone = ?", (phone,))
                    return False
                ok = str(row["code"]) == str(code).strip()
                if ok:
                    conn.execute("DELETE FROM sms_otp WHERE phone = ?", (phone,))
                return ok
            finally:
                conn.close()


# Back-compat alias
UserRegistry = SqliteUserRegistry


def get_user_registry():
    """Return SQLite or PostgreSQL registry per ``app_gateway.user_registry_backend``."""
    from plugins.app_gateway.user_registry_factory import get_user_registry as _get

    return _get()


def reset_user_registry_cache() -> None:
    from plugins.app_gateway.user_registry_factory import reset_user_registry_cache as _reset

    _reset()
