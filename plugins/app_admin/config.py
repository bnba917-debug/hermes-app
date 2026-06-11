"""Configuration for the standalone App Admin service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict

import yaml


@dataclass(frozen=True)
class AppAdminConfig:
    host: str = "127.0.0.1"
    port: int = 8790
    postgres_url: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    session_secret: str = ""


def _load_yaml_config() -> Dict[str, Any]:
    try:
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "config.yaml"
        if not path.is_file():
            return {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def load_app_admin_config() -> AppAdminConfig:
    raw = _load_yaml_config()
    cfg = raw.get("app_admin") if isinstance(raw.get("app_admin"), dict) else {}
    storage = raw.get("storage") if isinstance(raw.get("storage"), dict) else {}
    postgres_url = (
        os.environ.get("APP_ADMIN_POSTGRES_URL", "").strip()
        or str(cfg.get("postgres_url") or "").strip()
        or os.environ.get("APP_GATEWAY_POSTGRES_URL", "").strip()
        or os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
        or str(storage.get("postgres_url") or "").strip()
    )
    admin_username = (
        os.environ.get("APP_ADMIN_USERNAME", "").strip()
        or str(cfg.get("admin_username") or "").strip()
        or "admin"
    )
    admin_password = (
        os.environ.get("APP_ADMIN_PASSWORD", "").strip()
        or str(cfg.get("admin_password") or "").strip()
    )
    session_secret = (
        os.environ.get("APP_ADMIN_SESSION_SECRET", "").strip()
        or str(cfg.get("session_secret") or "").strip()
    )
    return AppAdminConfig(
        host=(
            os.environ.get("APP_ADMIN_HOST", "").strip()
            or str(cfg.get("host") or "").strip()
            or "127.0.0.1"
        ),
        port=int(
            os.environ.get("APP_ADMIN_PORT", "").strip()
            or cfg.get("port")
            or 8790
        ),
        postgres_url=postgres_url,
        admin_username=admin_username,
        admin_password=admin_password,
        session_secret=session_secret,
    )
