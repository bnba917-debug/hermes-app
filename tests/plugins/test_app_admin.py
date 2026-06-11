"""Standalone App Admin tests."""

from __future__ import annotations

import pytest


class FakeSkillRegistry:
    def __init__(self) -> None:
        self.items = {}

    def list_skills(self, **kwargs):
        return sorted(self.items.values(), key=lambda x: x["name"])

    def upsert_skill(self, **kwargs):
        current = self.items.get(kwargs["name"])
        version = int((current or {}).get("version") or 0) + 1
        files = kwargs.get("files")
        if files is None and current:
            files = current.get("files", {})
        elif files is None:
            files = {}
        item = {
            "id": version,
            "name": kwargs["name"],
            "visibility": kwargs.get("visibility", "public"),
            "owner_user_id": kwargs.get("owner_user_id"),
            "status": kwargs.get("status", "active"),
            "description": kwargs.get("description") or "Public skill",
            "skill_md": kwargs["skill_md"],
            "files": files,
            "version": version,
            "created_at": 1.0,
            "updated_at": 2.0,
        }
        self.items[kwargs["name"]] = item
        return item

    def get_skill(self, name, **kwargs):
        return self.items.get(name)

    def delete_skill(self, name, **kwargs):
        return self.items.pop(name, None) is not None


def test_app_admin_requires_postgres_url(monkeypatch):
    monkeypatch.delenv("APP_ADMIN_POSTGRES_URL", raising=False)
    monkeypatch.delenv("APP_GATEWAY_POSTGRES_URL", raising=False)
    monkeypatch.delenv("HERMES_STORAGE_POSTGRES_URL", raising=False)

    from plugins.app_admin.config import load_app_admin_config

    cfg = load_app_admin_config()
    assert cfg.postgres_url == ""


def test_app_admin_login_and_public_skill_crud():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from plugins.app_admin.config import AppAdminConfig
    from plugins.app_admin.server import create_app

    registry = FakeSkillRegistry()
    app = create_app(
        AppAdminConfig(
            postgres_url="postgresql://example",
            admin_username="admin",
            admin_password="secret",
            session_secret="session-secret",
        ),
        skill_registry=registry,
    )
    client = TestClient(app)

    denied = client.get("/api/skills")
    assert denied.status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    created = client.post(
        "/api/skills",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "public-demo",
            "skill_md": "---\nname: public-demo\ndescription: Public skill\n---\n",
        },
    )
    assert created.status_code == 200
    assert created.json()["skill"]["name"] == "public-demo"

    listed = client.get("/api/skills", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()["skills"]] == ["public-demo"]

    deleted = client.delete(
        "/api/skills/public-demo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["removed"] is True


def test_app_admin_save_skill_with_files():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from plugins.app_admin.config import AppAdminConfig
    from plugins.app_admin.server import create_app

    registry = FakeSkillRegistry()
    client = TestClient(
        create_app(
            AppAdminConfig(
                postgres_url="postgresql://example",
                admin_username="admin",
                admin_password="secret",
                session_secret="session-secret",
            ),
            skill_registry=registry,
        )
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    token = login.json()["access_token"]
    created = client.post(
        "/api/skills",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "with-files",
            "skill_md": "---\nname: with-files\ndescription: Has scripts.\n---\n\n# With Files\n",
            "files": {"scripts/run.py": "print('ok')\n"},
        },
    )
    assert created.status_code == 200
    assert created.json()["skill"]["files"]["scripts/run.py"] == "print('ok')\n"

    detail = client.get(
        "/api/skills/with-files",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["skill"]["files"]["scripts/run.py"] == "print('ok')\n"


def test_app_admin_rejects_app_gateway_signed_token():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from plugins.app_admin.config import AppAdminConfig
    from plugins.app_admin.server import create_app
    from plugins.app_gateway.auth import encode_hs256_jwt

    app = create_app(
        AppAdminConfig(
            postgres_url="postgresql://example",
            admin_username="admin",
            admin_password="secret",
            session_secret="admin-secret",
        ),
        skill_registry=FakeSkillRegistry(),
    )
    token = encode_hs256_jwt(
        {"sub": "admin", "role": "admin"},
        "admin-secret",
    )
    resp = TestClient(app).get(
        "/api/skills",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
