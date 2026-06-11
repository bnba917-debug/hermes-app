"""Audit facade — SQLite / PostgreSQL / dual (phase 2)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from plugins.app_gateway.audit_backends import AuditBackend, create_audit_backend
from plugins.app_gateway.config import AppGatewayConfig


class AuditStore:
    def __init__(self, config: AppGatewayConfig) -> None:
        self._backend: Optional[AuditBackend] = create_audit_backend(
            config.audit_backend,
            enabled=config.audit_enabled,
            postgres_url=config.postgres_url,
            postgres_only=bool(getattr(config, "postgres_only", False)),
        )

    @property
    def postgres_active(self) -> bool:
        return (self._backend is not None) and (
            getattr(self._backend, "__class__", None).__name__
            in ("PostgresAuditBackend", "CompositeAuditBackend")
        )

    def log(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: str,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._backend is None:
            return
        self._backend.log(
            user_id=user_id,
            session_id=session_id,
            event_type=event_type,
            device_id=device_id,
            payload=payload,
        )

    def log_feedback(
        self,
        *,
        user_id: str,
        session_id: str,
        rating: str,
        comment: str = "",
        message_id: str = "",
    ) -> None:
        self.log(
            user_id=user_id,
            session_id=session_id,
            event_type="feedback",
            payload={
                "rating": rating,
                "comment": comment,
                "message_id": message_id,
            },
        )
