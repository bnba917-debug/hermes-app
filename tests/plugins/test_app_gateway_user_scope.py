"""Per-user skill isolation for app gateway."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_user_homes_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.user_scope import ensure_user_home, user_hermes_home
    from plugins.app_gateway.auth import UserContext

    ensure_user_home("alice")
    ensure_user_home("bob")
    assert user_hermes_home("alice") != user_hermes_home("bob")

    alice_skill = user_hermes_home("alice") / "skills" / "my-skill" / "SKILL.md"
    alice_skill.parent.mkdir(parents=True)
    alice_skill.write_text(
        "---\nname: my-skill\ndescription: Alice only.\n---\n",
        encoding="utf-8",
    )

    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    from plugins.app_gateway.user_scope import app_gateway_user_scope
    from hermes_constants import get_hermes_home

    with app_gateway_user_scope(ctx):
        assert get_hermes_home() == user_hermes_home("alice")
        from agent.skill_utils import get_skills_dir

        assert (get_skills_dir() / "my-skill" / "SKILL.md").is_file()

    with app_gateway_user_scope(
        UserContext(user_id="bob", session_id="s1", device_id=None, raw_claims={}),
    ):
        assert not (get_skills_dir() / "my-skill" / "SKILL.md").is_file()


def test_operator_paths_ignore_per_user_hermes_home_env(tmp_path, monkeypatch):
    """Operator roots must not nest when HERMES_HOME points at a user tree."""
    operator = tmp_path / ".hermes"
    user_home = operator / "app_gateway" / "users" / "alice"
    user_home.mkdir(parents=True)
    (operator / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "app_gateway": {
                    "workspace_backend": "minio",
                    "audit_backend": "postgres",
                    "postgres_url": "postgresql://hermes:hermes@127.0.0.1:5432/hermes",
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(user_home))
    monkeypatch.setattr(
        "plugins.app_gateway.user_scope._use_postgres_user_data",
        lambda: True,
    )
    monkeypatch.setattr(
        "plugins.app_gateway.user_data_store.ensure_user_profile",
        lambda user_id: {"config": {}, "env_secrets": {}},
    )
    monkeypatch.setattr(
        "plugins.app_gateway.user_scope._apply_public_db_skills_catalog",
        lambda home, user_id: None,
    )
    monkeypatch.setattr(
        "plugins.app_gateway.user_scope._apply_shared_skills_catalog",
        lambda home, user_id: None,
    )
    monkeypatch.setattr(
        "plugins.app_gateway.user_scope._link_global_skills_catalog",
        lambda home, skills_dir, user_id: None,
    )
    monkeypatch.setattr(
        "plugins.app_gateway.workspace_backend.get_workspace_backend",
        lambda: type(
            "Backend",
            (),
            {
                "local_root": staticmethod(
                    lambda user_id: operator / "app_gateway" / "workspace-cache" / user_id
                )
            },
        )(),
    )

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.user_scope import (
        app_gateway_user_scope,
        ensure_user_home,
        operator_app_gateway_root,
        user_hermes_home,
    )

    assert operator_app_gateway_root().resolve() == (operator / "app_gateway").resolve()
    assert user_hermes_home("alice").resolve() == user_home.resolve()

    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    with app_gateway_user_scope(ctx):
        ensure_user_home("alice")
        from plugins.app_gateway.config import load_app_gateway_config

        cfg = load_app_gateway_config()
        assert cfg.workspace_backend == "minio"
        assert cfg.audit_backend == "postgres"

    assert not (user_home / "app_gateway").exists()


def test_skills_prompt_cache_key_includes_user_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes" / "skills").mkdir(parents=True)

    from gateway.session_context import set_session_vars, clear_session_vars
    from agent.prompt_builder import clear_skills_system_prompt_cache, build_skills_system_prompt

    clear_skills_system_prompt_cache()
    tokens_a = set_session_vars(user_id="user-a", platform="app_gateway")
    build_skills_system_prompt(available_tools=set(), available_toolsets=set())
    clear_session_vars(tokens_a)

    tokens_b = set_session_vars(user_id="user-b", platform="app_gateway")
    build_skills_system_prompt(available_tools=set(), available_toolsets=set())
    clear_session_vars(tokens_b)

    from agent import prompt_builder as pb

    keys = list(pb._SKILLS_PROMPT_CACHE.keys())
    user_hints = {k[5] for k in keys if len(k) > 5}
    assert "user-a" in user_hints or "user-b" in user_hints
