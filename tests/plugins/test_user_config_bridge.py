"""In-memory user config/env overrides for scoped App Gateway users."""

from __future__ import annotations


def test_user_config_override_bypasses_missing_config_file(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli.config import (
        load_config,
        load_env,
        reset_user_config_override,
        reset_user_env_override,
        set_user_config_override,
        set_user_env_override,
    )

    cfg_token = set_user_config_override(
        {
            "model": {"provider": "openrouter", "default": "test-model"},
            "skills": {"disabled": ["a"]},
        }
    )
    env_token = set_user_env_override({"OPENROUTER_API_KEY": "scoped-key"})
    try:
        cfg = load_config()
        env = load_env()
    finally:
        reset_user_env_override(env_token)
        reset_user_config_override(cfg_token)

    assert cfg["model"]["default"] == "test-model"
    assert env["OPENROUTER_API_KEY"] == "scoped-key"
    assert not (home / "config.yaml").is_file()


def test_external_skills_dirs_override(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    ext = tmp_path / "external-skills"
    ext.mkdir()
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    from agent.skill_utils import (
        get_external_skills_dirs,
        reset_external_skills_dirs_override,
        set_external_skills_dirs_override,
    )

    token = set_external_skills_dirs_override([ext])
    try:
        dirs = get_external_skills_dirs()
    finally:
        reset_external_skills_dirs_override(token)

    assert dirs == [ext.resolve()]
