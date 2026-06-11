"""PostgreSQL-backed per-user config."""

from __future__ import annotations

import os

import pytest
import yaml


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
def pg_user_data(tmp_path, monkeypatch):
    url = _postgres_url()
    if not _pg_available(url):
        pytest.skip("PostgreSQL not available")

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_STORAGE_POSTGRES_URL", url)

    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {"postgres_url": url},
                "app_gateway": {
                    "jwt_secret": "test-secret",
                    "postgres_url": url,
                    "enabled": True,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    from plugins.app_gateway.user_data_store import reset_user_data_store_cache

    reset_user_data_store_cache()

    try:
        import psycopg

        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE hermes_app_skill_files, hermes_app_skills, "
                    "hermes_app_user_profiles RESTART IDENTITY CASCADE"
                )
    except Exception:
        pass

    yield url
    reset_user_data_store_cache()


def test_user_profile_roundtrip(pg_user_data):
    from plugins.app_gateway.user_data_store import (
        ensure_user_profile,
        get_user_data_store,
        save_user_profile,
    )

    profile = ensure_user_profile("u-pg")
    assert profile["user_id"] == "u-pg"
    assert profile["config"]["model"]["provider"] == "openrouter"

    cfg = dict(profile["config"])
    cfg["model"]["default"] = "test-model"
    saved = save_user_profile(
        "u-pg",
        config=cfg,
        env_secrets={"OPENROUTER_API_KEY": "secret-key"},
    )
    assert saved["config"]["model"]["default"] == "test-model"
    assert saved["env_secrets"]["OPENROUTER_API_KEY"] == "secret-key"

    reloaded = get_user_data_store().get_profile("u-pg")
    assert reloaded["config"]["model"]["default"] == "test-model"


def test_hydrate_user_profile_writes_home_files(pg_user_data, tmp_path):
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_config_bridge import build_runtime_user_config
    from plugins.app_gateway.user_data_store import save_user_profile
    from plugins.app_gateway.user_scope import app_gateway_user_scope, user_hermes_home

    save_user_profile(
        "u-hydrate",
        config={
            "model": {"provider": "deepseek", "default": "deepseek-chat"},
            "skills": {"disabled": ["x-skill"]},
            "approvals": {"mode": "off"},
            "app_gateway": {"user_id": "u-hydrate"},
        },
        env_secrets={"DEEPSEEK_API_KEY": "ds-key"},
    )
    home = user_hermes_home("u-hydrate")
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg, env = build_runtime_user_config("u-hydrate", home=home, workspace=workspace)
    assert cfg["model"]["default"] == "deepseek-chat"
    assert "x-skill" in cfg["skills"]["disabled"]
    assert env["DEEPSEEK_API_KEY"] == "ds-key"
    assert not (home / "config.yaml").is_file()

    ctx = UserContext(user_id="u-hydrate", session_id="s1", device_id=None, raw_claims={})
    with app_gateway_user_scope(ctx, include_global_skills=False):
        from hermes_cli.config import load_config, load_env

        loaded_cfg = load_config()
        loaded_env = load_env()
    assert loaded_cfg["model"]["default"] == "deepseek-chat"
    assert loaded_env["DEEPSEEK_API_KEY"] == "ds-key"
    assert not (home / "config.yaml").is_file()


def test_set_skills_disabled_persists_in_db(pg_user_data):
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.skills_service import get_skills_config, set_skills_disabled
    from plugins.app_gateway.user_data_store import get_user_data_store
    from plugins.app_gateway.user_scope import ensure_user_home

    ctx = UserContext(user_id="u-dis", session_id="s1", device_id=None, raw_claims={})
    ensure_user_home("u-dis")
    set_skills_disabled(ctx, ["alpha", "beta"])
    cfg = get_skills_config(ctx)
    assert cfg["storage"] == "postgres"
    assert "alpha" in cfg["disabled"]

    profile = get_user_data_store().get_profile("u-dis")
    assert "alpha" in profile["config"]["skills"]["disabled"]


def test_inference_config_persists_in_db(pg_user_data):
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_credentials import set_user_inference_config
    from plugins.app_gateway.user_data_store import get_user_data_store
    from plugins.app_gateway.user_scope import ensure_user_home

    ctx = UserContext(user_id="u-inf", session_id="s1", device_id=None, raw_claims={})
    ensure_user_home("u-inf")
    set_user_inference_config(
        ctx,
        api_key="user-only-key",
        provider="openrouter",
        model="anthropic/claude-sonnet-4",
    )
    profile = get_user_data_store().get_profile("u-inf")
    assert profile["config"]["model"]["default"] == "anthropic/claude-sonnet-4"
    assert profile["env_secrets"]["OPENROUTER_API_KEY"] == "user-only-key"
