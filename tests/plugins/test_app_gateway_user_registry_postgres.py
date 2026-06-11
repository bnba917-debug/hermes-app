"""PostgreSQL app user registry."""

from __future__ import annotations

import os

import pytest


def _postgres_url() -> str:
    return (
        os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
        or os.environ.get("TEST_POSTGRES_URL", "").strip()
        or "postgresql://hermes:hermes_dev@127.0.0.1:5432/hermes"
    )


def _pg_available(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture
def pg_registry(tmp_path, monkeypatch):
    url = _postgres_url()
    if not _pg_available(url):
        pytest.skip("PostgreSQL not available")

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", url)

    import yaml

    (home / "config.yaml").write_text(
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

    from plugins.app_gateway.user_registry_factory import (
        create_user_registry,
        reset_user_registry_cache,
    )

    reset_user_registry_cache()
    reg = create_user_registry(backend="postgres", dsn=url)

    try:
        import psycopg

        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE hermes_app_sms_otp, hermes_app_users RESTART IDENTITY")
    except Exception:
        pass

    yield reg
    reset_user_registry_cache()


def test_postgres_register_and_onboarding(pg_registry):
    from plugins.app_gateway.config import load_app_gateway_config
    from plugins.app_gateway.phone_auth import normalize_phone, send_sms_code, verify_phone_login
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.onboarding import complete_onboarding, onboarding_status

    cfg = load_app_gateway_config()
    phone = normalize_phone("13900139000")
    send_sms_code(cfg, phone)
    record, token, is_new = verify_phone_login(
        cfg, phone=phone, code=cfg.dev_sms_code, device_id="d1"
    )
    assert is_new
    assert pg_registry.get_by_phone(phone) is not None

    ctx = UserContext(
        user_id=record.user_id,
        session_id="app",
        device_id="d1",
        raw_claims={"sub": record.user_id},
    )
    assert onboarding_status(ctx)["initialized"] is False
    complete_onboarding(
        ctx,
        api_key="k",
        model="m",
        provider="openrouter",
    )
    updated = pg_registry.get_by_user_id(record.user_id)
    assert updated and updated.initialized_at is not None


def test_resolve_auto_uses_postgres_when_dsn(tmp_path, monkeypatch):
    url = _postgres_url()
    if not _pg_available(url):
        pytest.skip("PostgreSQL not available")

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    import yaml

    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {"storage": {"postgres_url": url}, "app_gateway": {"user_registry_backend": "auto"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    from plugins.app_gateway.user_registry_factory import resolve_user_registry_backend

    backend, dsn = resolve_user_registry_backend()
    assert backend == "postgres"
    assert dsn == url
