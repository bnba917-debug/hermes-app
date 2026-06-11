"""Standalone FastAPI server for the App Admin console."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from plugins.app_admin.auth import (
    issue_admin_token,
    verify_admin_password,
    verify_admin_token,
)
from plugins.app_admin.config import AppAdminConfig, load_app_admin_config
from plugins.app_admin.db import apply_schema
from plugins.app_gateway.auth import JwtError, parse_bearer_token
from plugins.app_gateway.skill_registry import SkillRegistry


def _web_index() -> str:
    path = Path(__file__).parent / "web" / "index.html"
    return path.read_text(encoding="utf-8")


def create_app(
    config: Optional[AppAdminConfig] = None,
    *,
    skill_registry: Optional[Any] = None,
) -> FastAPI:
    cfg = config or load_app_admin_config()
    registry = skill_registry

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if cfg.postgres_url and skill_registry is None:
            apply_schema(cfg.postgres_url)
        yield

    app = FastAPI(title="Hermes App Admin", version="0.1.0", lifespan=lifespan)

    def _registry():
        nonlocal registry
        if registry is None:
            if not cfg.postgres_url:
                raise HTTPException(status_code=503, detail="PostgreSQL URL is required")
            registry = SkillRegistry(cfg.postgres_url)
        return registry

    def _require_admin(authorization: Optional[str]) -> str:
        token = parse_bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="Admin token required")
        try:
            claims = verify_admin_token(token, cfg.session_secret)
        except (JwtError, RuntimeError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return str(claims.get("sub") or "admin")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(_web_index())

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "postgres_configured": bool(cfg.postgres_url),
            "admin_login_configured": bool(cfg.admin_password and cfg.session_secret),
        }

    @app.post("/api/auth/login")
    async def login(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if username != cfg.admin_username or not verify_admin_password(
            password,
            cfg.admin_password,
        ):
            raise HTTPException(status_code=401, detail="Invalid admin credentials")
        return {
            "access_token": issue_admin_token(username, cfg.session_secret),
            "token_type": "bearer",
        }

    @app.get("/api/skills")
    async def list_skills(authorization: Optional[str] = Header(None)):
        _require_admin(authorization)
        skills = _registry().list_skills(
            visibility="public",
            include_disabled=True,
            include_body=False,
            include_files=False,
        )
        from plugins.app_gateway.skill_files import list_skill_file_summaries

        for skill in skills:
            detail = _registry().get_skill(skill["name"], visibility="public", include_files=True)
            skill["files"] = list_skill_file_summaries((detail or {}).get("files"))
        return {"ok": True, "skills": skills}

    @app.get("/api/skills/{name}")
    async def get_skill(name: str, authorization: Optional[str] = Header(None)):
        _require_admin(authorization)
        skill = _registry().get_skill(name, visibility="public", include_disabled=True)
        if not skill:
            raise HTTPException(status_code=404, detail="skill not found")
        return {"ok": True, "skill": skill}

    @app.post("/api/skills")
    async def upsert_skill(
        request: Request,
        authorization: Optional[str] = Header(None),
    ):
        actor = _require_admin(authorization)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        raw_files = body.get("files")
        files = raw_files if isinstance(raw_files, dict) else None
        try:
            skill = _registry().upsert_skill(
                name=str(body.get("name") or ""),
                skill_md=str(body.get("skill_md") or ""),
                visibility="public",
                status=str(body.get("status") or "active"),
                description=body.get("description"),
                files=files,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "actor": actor, "skill": skill}

    @app.post("/api/skills/import-zip")
    async def import_skill_zip(
        authorization: Optional[str] = Header(None),
        archive: UploadFile = File(...),
    ):
        actor = _require_admin(authorization)
        from plugins.app_gateway.skill_files import parse_skill_zip

        data = await archive.read()
        try:
            name, skill_md, files = parse_skill_zip(data)
            skill = _registry().upsert_skill(
                name=name,
                skill_md=skill_md,
                visibility="public",
                status="active",
                files=files,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "actor": actor, "skill": skill}

    @app.delete("/api/skills/{name}")
    async def delete_skill(name: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(authorization)
        removed = _registry().delete_skill(name, visibility="public")
        return {"ok": True, "actor": actor, "name": name, "removed": removed}

    @app.get("/api/users")
    async def users_placeholder(authorization: Optional[str] = Header(None)):
        _require_admin(authorization)
        return {"ok": True, "users": []}

    @app.get("/api/billing")
    async def billing_placeholder(authorization: Optional[str] = Header(None)):
        _require_admin(authorization)
        return {"ok": True, "wallets": [], "orders": []}

    return app


def main() -> None:
    import uvicorn

    cfg = load_app_admin_config()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
