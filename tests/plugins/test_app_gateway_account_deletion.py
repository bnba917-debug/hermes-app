"""Account deletion erases registry, profile, OTP, sessions, and user home."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from plugins.app_gateway.auth import UserContext


@pytest.fixture
def gateway_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from plugins.app_gateway.user_registry_factory import reset_user_registry_cache

    reset_user_registry_cache()
    yield home
    reset_user_registry_cache()


def test_sqlite_delete_user_clears_otp(gateway_home):
    from plugins.app_gateway.user_registry import SqliteUserRegistry

    reg = SqliteUserRegistry()
    reg.upsert_user("u_delete_otp", "8613800138001")
    reg.store_otp("8613800138001", "123456", ttl_seconds=300)

    assert reg.get_by_user_id("u_delete_otp") is not None
    conn = reg._connect()
    try:
        assert conn.execute(
            "SELECT 1 FROM sms_otp WHERE phone = ?", ("8613800138001",)
        ).fetchone()
    finally:
        conn.close()

    assert reg.delete_user("u_delete_otp") is True
    assert reg.get_by_user_id("u_delete_otp") is None
    conn = reg._connect()
    try:
        assert (
            conn.execute(
                "SELECT 1 FROM sms_otp WHERE phone = ?", ("8613800138001",)
            ).fetchone()
            is None
        )
    finally:
        conn.close()


def test_delete_user_account_removes_home_and_sessions(gateway_home):
    from hermes_state import get_shared_session_db
    from plugins.app_gateway.account_compliance import delete_user_account
    from plugins.app_gateway.session_keys import build_hermes_session_id
    from plugins.app_gateway.user_registry import SqliteUserRegistry
    from plugins.app_gateway.user_scope import user_hermes_home

    user_id = "u_delete_full"
    phone = "8613800138002"
    reg = SqliteUserRegistry()
    reg.upsert_user(user_id, phone)
    reg.store_otp(phone, "111111", ttl_seconds=300)

    home = user_hermes_home(user_id)
    home.mkdir(parents=True)
    (home / "skills" / "mine").mkdir(parents=True)
    (home / "skills" / "mine" / "SKILL.md").write_text("# mine", encoding="utf-8")

    ctx = UserContext(user_id=user_id, session_id="chat-1", device_id=None, raw_claims={})
    sid = build_hermes_session_id(ctx)
    db = get_shared_session_db()
    db.create_session(sid, "app_gateway", user_id=user_id)
    db.append_message(sid, "user", "hello")

    vector = type("V", (), {"delete_user": lambda self, uid: 1})()

    result = delete_user_account(ctx, vector_memory=vector)

    assert result["ok"] is True
    assert result["registry_deleted"] is True
    assert result["home_removed"] is True
    assert result["sessions_removed"] >= 1
    assert not home.exists()
    assert reg.get_by_user_id(user_id) is None
    assert db.get_session(sid) is None


def test_delete_user_account_removes_workspace_cache(gateway_home, monkeypatch):
    from plugins.app_gateway.account_compliance import delete_user_account
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.user_registry import SqliteUserRegistry
    from plugins.app_gateway.user_scope import operator_app_gateway_root
    from plugins.app_gateway.workspace_backend import reset_workspace_backend_cache

    reset_workspace_backend_cache()
    cfg = AppGatewayConfig(workspace_backend="minio", workspace_minio_async_upload=False)
    monkeypatch.setattr(
        "plugins.app_gateway.config.load_app_gateway_config",
        lambda: cfg,
    )

    user_id = "u_cache_delete"
    cache_root = operator_app_gateway_root() / "workspace-cache" / user_id
    cache_root.mkdir(parents=True)
    uploads = cache_root / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "orphan.bin").write_bytes(b"pending-upload")
    (cache_root / "prefetch.txt").write_text("cached-only", encoding="utf-8")

    reg = SqliteUserRegistry()
    reg.upsert_user(user_id, "8613800138010")

    fake_client = MagicMock()
    fake_client.bucket_exists.return_value = True
    fake_client.list_objects.return_value = []

    ctx = UserContext(user_id=user_id, session_id="app", device_id=None, raw_claims={})
    with patch(
        "plugins.app_gateway.workspace_minio._get_client",
        return_value=fake_client,
    ):
        result = delete_user_account(ctx, vector_memory=None)

    assert result["workspace_cache_removed"] is True
    assert not cache_root.exists()
    assert reg.get_by_user_id(user_id) is None


def _pg_cleanup_user(reg, store, user_id: str, phone: str, *, dsn: str) -> None:
    """Best-effort cleanup so PG tests stay idempotent across runs."""
    from plugins.app_gateway.account_compliance import delete_user_account
    from plugins.app_gateway.auth import UserContext

    ctx = UserContext(user_id=user_id, session_id="app", device_id=None, raw_claims={})
    if reg.get_by_user_id(user_id):
        delete_user_account(ctx)
    else:
        store.delete_profile(user_id)
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM hermes_app_sms_otp WHERE phone = %s", (phone,)
                    )
                conn.commit()
        except Exception:
            pass


def test_delete_user_account_deletes_postgres_profile(gateway_home, monkeypatch):
    url = (
        os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
        or os.environ.get("TEST_POSTGRES_URL", "").strip()
        or "postgresql://hermes:hermes_dev@127.0.0.1:5432/hermes"
    )
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=2):
            pass
    except Exception:
        pytest.skip("PostgreSQL not available")

    import yaml

    (gateway_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {"postgres_url": url},
                "app_gateway": {
                    "user_registry_backend": "postgres",
                    "postgres_url": url,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", url)

    from plugins.app_gateway.account_compliance import delete_user_account
    from plugins.app_gateway.user_data_store import (
        get_user_data_store,
        reset_user_data_store_cache,
    )
    from plugins.app_gateway.user_registry_factory import (
        create_user_registry,
        reset_user_registry_cache,
    )

    reset_user_registry_cache()
    reset_user_data_store_cache()
    reg = create_user_registry(backend="postgres", dsn=url)
    store = get_user_data_store()

    user_id = "u_delete_profile_test"
    phone = "8613800138099"
    _pg_cleanup_user(reg, store, user_id, phone, dsn=url)
    reg = create_user_registry(backend="postgres", dsn=url)

    reg.upsert_user(user_id, phone)
    reg.store_otp(phone, "111111", ttl_seconds=300)
    store.save_profile(
        user_id,
        config={
            "model": {"default": "kimi-k2.6", "provider": "kimi-coding-cn"},
            "app_gateway": {"user_id": user_id},
        },
        env_secrets={"KIMI_CN_API_KEY": "secret-key"},
    )

    ctx = UserContext(user_id=user_id, session_id="app", device_id=None, raw_claims={})
    result = delete_user_account(ctx, vector_memory=None)

    assert result["profile_deleted"] is True
    assert store.get_profile(user_id) is None
    assert reg.get_by_user_id(user_id) is None

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM hermes_app_sms_otp WHERE phone = %s", (phone,)
            )
            assert cur.fetchone() is None


def test_relogin_after_delete_gets_fresh_onboarding(gateway_home, monkeypatch):
    url = (
        os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
        or os.environ.get("TEST_POSTGRES_URL", "").strip()
        or "postgresql://hermes:hermes_dev@127.0.0.1:5432/hermes"
    )
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=2):
            pass
    except Exception:
        pytest.skip("PostgreSQL not available")

    import yaml

    (gateway_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {"postgres_url": url},
                "app_gateway": {
                    "jwt_secret": "test-secret",
                    "auth_mode": "dev",
                    "dev_sms_code": "111111",
                    "user_registry_backend": "postgres",
                    "postgres_url": url,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", url)

    from plugins.app_gateway.account_compliance import delete_user_account
    from plugins.app_gateway.config import AppGatewayConfig, load_app_gateway_config
    from plugins.app_gateway.onboarding import onboarding_status
    from plugins.app_gateway.phone_auth import normalize_phone, send_sms_code, user_id_for_phone, verify_phone_login
    from plugins.app_gateway.user_data_store import (
        ensure_user_profile,
        get_user_data_store,
        reset_user_data_store_cache,
    )
    from plugins.app_gateway.user_registry_factory import (
        create_user_registry,
        reset_user_registry_cache,
    )

    reset_user_registry_cache()
    reset_user_data_store_cache()

    cfg = load_app_gateway_config()
    phone = normalize_phone("13900139999")
    send_sms_code(cfg, phone)
    reg = create_user_registry(backend="postgres", dsn=url)
    store = get_user_data_store()
    _pg_cleanup_user(reg, store, user_id_for_phone(phone), phone, dsn=url)
    reset_user_registry_cache()

    record, _, is_new = verify_phone_login(
        cfg, phone=phone, code="111111", device_id="d1"
    )
    assert is_new

    store = get_user_data_store()
    store.save_profile(
        record.user_id,
        config={
            "model": {"default": "kimi-k2.6", "provider": "kimi-coding-cn"},
            "app_gateway": {"user_id": record.user_id},
        },
        env_secrets={"KIMI_CN_API_KEY": "old-secret"},
    )

    ctx = UserContext(
        user_id=record.user_id,
        session_id="app",
        device_id="d1",
        raw_claims={"sub": record.user_id},
    )
    delete_user_account(ctx)

    send_sms_code(cfg, phone)
    record2, _, is_new2 = verify_phone_login(
        cfg, phone=phone, code="111111", device_id="d1"
    )
    assert is_new2
    assert record2.user_id == record.user_id

    ctx2 = UserContext(
        user_id=record2.user_id,
        session_id="app",
        device_id="d1",
        raw_claims={"sub": record2.user_id},
    )
    profile = ensure_user_profile(record2.user_id)
    assert profile.get("env_secrets") == {}
    assert onboarding_status(ctx2)["initialized"] is False
