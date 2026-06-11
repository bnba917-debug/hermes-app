"""PostgreSQL helpers and schema for App Admin."""

from __future__ import annotations

from typing import Iterable


APP_ADMIN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_admin_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    status TEXT NOT NULL DEFAULT 'active',
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS app_admin_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS user_wallets (
    user_id TEXT PRIMARY KEY,
    balance_cents BIGINT NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    amount_cents BIGINT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    reason TEXT NOT NULL,
    admin_actor TEXT,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS recharge_orders (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    amount_cents BIGINT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    status TEXT NOT NULL DEFAULT 'pending',
    provider TEXT,
    provider_order_id TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
"""


def connect(postgres_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "App Admin requires PostgreSQL via psycopg. Install: uv pip install -e '.[postgres]'"
        ) from exc
    if not str(postgres_url or "").strip():
        raise RuntimeError("APP_ADMIN_POSTGRES_URL or APP_GATEWAY_POSTGRES_URL is required")
    return psycopg.connect(postgres_url, row_factory=dict_row)


def apply_schema(postgres_url: str, extra_sql: Iterable[str] = ()) -> None:
    with connect(postgres_url) as conn:
        with conn.cursor() as cur:
            cur.execute(APP_ADMIN_SCHEMA_SQL)
            for sql in extra_sql:
                cur.execute(sql)
        conn.commit()
