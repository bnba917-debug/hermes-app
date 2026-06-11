"""App Gateway skill library — save, config, shared catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


def test_skill_manage_create_respects_hermes_home_override(tmp_path, monkeypatch):
    """Regression: _resolve_skill_dir must not use import-time SKILLS_DIR."""
    profile = tmp_path / "profile-x"
    monkeypatch.setenv("HERMES_HOME", str(profile))
    profile.mkdir(parents=True)

    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.skill_manager_tool import _create_skill, _resolve_skill_dir

    content = """---
name: scoped-skill
description: Scoped to overridden home.
---

# Scoped

## Procedure

Use this skill to verify profile-scoped skill creation.
"""
    token = set_hermes_home_override(profile)
    try:
        assert _resolve_skill_dir("scoped-skill") == profile / "skills" / "scoped-skill"
        raw = _create_skill("scoped-skill", content)
        data = raw if isinstance(raw, dict) else json.loads(raw)
        assert data.get("success") is True
        assert (profile / "skills" / "scoped-skill" / "SKILL.md").is_file()
    finally:
        reset_hermes_home_override(token)


def test_set_skills_disabled_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.skills_service import set_skills_disabled, get_skills_config
    from plugins.app_gateway.user_scope import ensure_user_home

    ctx = UserContext(user_id="u2", session_id="s1", device_id=None, raw_claims={})
    ensure_user_home("u2")
    out = set_skills_disabled(ctx, ["foo-skill", "bar-skill"])
    assert out["disabled"] == ["bar-skill", "foo-skill"]
    cfg = get_skills_config(ctx)
    assert "foo-skill" in cfg["disabled"]


def test_shared_skills_merged_into_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    shared = tmp_path / "shared-skills"
    shared.mkdir()
    (shared / "ops-skill" / "SKILL.md").parent.mkdir(parents=True)
    (shared / "ops-skill" / "SKILL.md").write_text(
        "---\nname: ops-skill\ndescription: Shared ops skill.\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plugins.app_gateway.config.load_app_gateway_config",
        lambda: type(
            "Cfg",
            (),
            {
                "enable_shared_skills": True,
                "shared_skills_dir": str(shared),
            },
        )(),
    )

    from plugins.app_gateway.user_scope import ensure_user_home, user_hermes_home

    home = ensure_user_home("u3")
    raw = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    ext = raw.get("skills", {}).get("external_dirs") or []
    assert any(str(shared.resolve()) in str(Path(x).resolve()) for x in ext)


def test_load_app_gateway_config_reads_operator_jwt_when_user_home_set(
    tmp_path, monkeypatch
):
    operator = tmp_path / ".hermes"
    user_home = operator / "app_gateway" / "users" / "u1"
    user_home.mkdir(parents=True)
    (operator / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "app_gateway": {
                    "jwt_secret": "operator-jwt-secret",
                    "enabled": True,
                    "audit_backend": "postgres",
                    "vector_memory_backend": "postgres",
                    "user_registry_backend": "postgres",
                    "workspace_backend": "minio",
                    "postgres_url": "postgresql://hermes:hermes@127.0.0.1:5432/hermes",
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (user_home / "config.yaml").write_text(
        yaml.safe_dump(
            {"app_gateway": {"jwt_secret": "", "enabled": False}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(user_home))
    monkeypatch.delenv("APP_GATEWAY_JWT_SECRET", raising=False)

    from plugins.app_gateway.config import load_app_gateway_config

    cfg = load_app_gateway_config()
    assert cfg.jwt_secret == "operator-jwt-secret"
    assert cfg.audit_backend == "postgres"
    assert cfg.workspace_backend == "minio"
    assert cfg.user_registry_backend == "postgres"


def test_bundled_skills_external_dir_fallback_when_symlink_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    def fail_symlink(*args, **kwargs):
        raise OSError("symlink unavailable")

    monkeypatch.setattr(Path, "symlink_to", fail_symlink)
    monkeypatch.setattr(
        "plugins.app_gateway.user_scope._try_link_bundled_skills",
        lambda _link, _bundled: False,
    )

    from plugins.app_gateway.user_scope import ensure_user_home

    home = ensure_user_home("u-bundled")
    raw = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    ext = raw.get("skills", {}).get("external_dirs") or []
    repo_skills = Path(__file__).resolve().parents[2] / "skills"
    assert any(Path(x).resolve() == repo_skills.resolve() for x in ext)


def test_skill_inventory_query_gets_visible_catalog_prompt():
    from plugins.app_gateway.runtime import (
        _format_visible_skills_catalog,
        _looks_like_skill_inventory_query,
    )

    assert _looks_like_skill_inventory_query("你有哪些skills？")

    block = _format_visible_skills_catalog(
        [
            {"name": "airtable", "description": "Manage Airtable records."},
            {"name": "arxiv", "description": "Search arXiv papers."},
        ]
    )

    assert "Visible skills catalog" in block
    assert "Do not say you cannot access skills" in block
    assert "Do not answer that the user has no saved skills" in block
    assert "airtable: Manage Airtable records." in block
    assert "arxiv: Search arXiv papers." in block


def test_public_skill_registry_requires_postgres_dsn():
    from plugins.app_gateway.skill_registry import SkillRegistry

    with pytest.raises(RuntimeError, match="PostgreSQL DSN"):
        SkillRegistry("")


def test_public_registry_skills_are_visible_to_app_users(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.skills_routes import list_user_skills
    from plugins.app_gateway.skills_service import get_user_skill

    class FakeRegistry:
        def list_skills(self, **kwargs):
            return [
                {
                    "name": "db-public",
                    "description": "Public DB-backed skill.",
                    "version": 1,
                }
            ]

        def get_skill(self, name, **kwargs):
            return {
                "name": name,
                "description": "Public DB-backed skill.",
                "version": 1,
                "skill_md": (
                    "---\n"
                    "name: db-public\n"
                    "description: Public DB-backed skill.\n"
                    "---\n\n"
                    "# DB Public\n"
                ),
            }

    monkeypatch.setattr(
        "plugins.app_gateway.skill_registry.get_skill_registry",
        lambda: FakeRegistry(),
    )
    ctx = UserContext(user_id="u-db", session_id="app", device_id=None, raw_claims={})

    names = {s["name"]: s for s in list_user_skills(ctx, include_global=False)}
    assert names["db-public"]["scope"] == "public"

    detail = get_user_skill(ctx, "db-public")
    assert detail["scope"] == "public"
    assert "Public DB-backed skill." in detail["skill_md"]


def test_user_skill_shadows_db_public_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.skills_routes import list_user_skills
    from plugins.app_gateway.skills_service import get_user_skill
    from plugins.app_gateway.user_scope import ensure_user_home

    class FakeRegistry:
        def list_skills(self, **kwargs):
            return [
                {
                    "name": "same-name",
                    "description": "Public copy.",
                    "version": 1,
                }
            ]

        def get_skill(self, name, **kwargs):
            return {
                "name": name,
                "description": "Public copy.",
                "version": 1,
                "skill_md": "---\nname: same-name\ndescription: Public copy.\n---\n\n# Public\n",
            }

    monkeypatch.setattr(
        "plugins.app_gateway.skill_registry.get_skill_registry",
        lambda: FakeRegistry(),
    )
    ctx = UserContext(user_id="u-shadow", session_id="app", device_id=None, raw_claims={})
    home = ensure_user_home("u-shadow")
    skill_dir = home / "skills" / "same-name"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        (
            "---\n"
            "name: same-name\n"
            "description: Local copy.\n"
            "---\n\n"
            "# Local\n\n"
            "## Procedure\n\n"
            "Use this local copy.\n"
        ),
        encoding="utf-8",
    )

    listed = {s["name"]: s for s in list_user_skills(ctx, include_global=False)}
    assert listed["same-name"]["scope"] == "user"

    detail = get_user_skill(ctx, "same-name")
    assert detail["scope"] == "user"
    assert "Local copy." in detail["skill_md"]


def test_gateway_admin_user_inference_requires_configured_app_key(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from fastapi.testclient import TestClient
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.server import create_app

    client = TestClient(
        create_app(
            AppGatewayConfig(
                require_jwt=False,
                jwt_secret="test-secret",
                app_key="",
                vector_memory_enabled=False,
            )
        )
    )

    resp = client.put(
        "/v1/admin/users/u-admin/inference",
        json={"provider": "openai", "model": "gpt-test", "api_key": "secret"},
    )
    assert resp.status_code == 503


def test_get_user_skill_after_file_skill_create(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.skills_service import get_user_skill
    from plugins.app_gateway.user_scope import ensure_user_home

    ctx = UserContext(user_id="u4", session_id="s1", device_id=None, raw_claims={})
    home = ensure_user_home("u4")
    skill_dir = home / "skills" / "readback"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        (
            "---\n"
            "name: readback\n"
            "description: Read back test.\n"
            "---\n\n"
            "# Readback\n\n"
            "## Procedure\n\n"
            "Use this skill to verify app gateway skill readback.\n"
        ),
        encoding="utf-8",
    )
    detail = get_user_skill(ctx, "readback")
    assert detail["name"] == "readback"
    assert detail["writable"] is True
    assert "readback" in detail["skill_md"]


def test_private_skill_upsert_rejected():
    from plugins.app_gateway.skill_registry import SkillRegistry

    registry = SkillRegistry.__new__(SkillRegistry)
    with pytest.raises(ValueError, match="private skills are not supported"):
        SkillRegistry.upsert_skill(
            registry,
            name="my-skill",
            skill_md="---\nname: my-skill\ndescription: Nope.\n---\n",
            visibility="private",
            owner_user_id="u1",
        )


def test_classify_skill_scope_three_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()
    monkeypatch.setattr(
        "plugins.app_gateway.user_scope._link_global_skills_catalog",
        lambda home, skills_dir, user_id=None: None,
    )

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.skill_files import materialize_public_skill, public_skills_root
    from plugins.app_gateway.skill_scope import classify_skill_scope
    from plugins.app_gateway.skills_routes import list_user_skills
    from plugins.app_gateway.user_scope import ensure_user_home, operator_app_gateway_root

    uid = "u-scope"
    home = ensure_user_home(uid)
    ctx = UserContext(user_id=uid, session_id="app", device_id=None, raw_claims={})

    agent_skill = home / "skills" / "agent-skill"
    agent_skill.mkdir(parents=True)
    agent_skill.joinpath("SKILL.md").write_text(
        "---\nname: agent-skill\ndescription: Mine.\n---\n\n# Agent\n",
        encoding="utf-8",
    )

    materialize_public_skill(
        "public-skill",
        "---\nname: public-skill\ndescription: Public.\n---\n\n# Public\n",
    )
    from plugins.app_gateway.skills_service import merge_shared_skills_into_user_config

    merge_shared_skills_into_user_config(home, public_skills_root(), user_id=uid)

    bundled_skill = home / "skills" / "_bundled" / "demo-skill"
    bundled_skill.mkdir(parents=True)
    bundled_skill.joinpath("SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Bundled.\n---\n\n# Bundled\n",
        encoding="utf-8",
    )

    assert classify_skill_scope(agent_skill, user_id=uid) == "user"
    assert classify_skill_scope(bundled_skill, user_id=uid) == "bundled_readonly"
    assert classify_skill_scope(public_skills_root() / "public-skill", user_id=uid) == "public"

    listed = {s["name"]: s["scope"] for s in list_user_skills(ctx, include_global=True)}
    assert listed["agent-skill"] == "user"
    assert listed["demo-skill"] == "bundled_readonly"
    assert listed["public-skill"] == "public"
    assert operator_app_gateway_root().name == "app_gateway"


def test_classify_repo_bundled_via_external_dirs():
    from pathlib import Path

    from plugins.app_gateway.skill_scope import classify_skill_scope

    repo = Path(__file__).resolve().parents[2] / "skills"
    sample = next(repo.rglob("SKILL.md"), None)
    assert sample is not None
    assert classify_skill_scope(sample.parent, user_id="u-external-bundled") == "bundled_readonly"
