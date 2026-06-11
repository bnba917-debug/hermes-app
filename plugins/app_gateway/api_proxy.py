"""Optional proxy to the built-in api_server (port 8642) with JWT → Hermes headers."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.session_keys import build_gateway_session_key, build_hermes_session_id

logger = logging.getLogger(__name__)


class ApiServerProxy:
    """Forwards OpenAI-compatible requests to ``gateway`` api_server."""

    def __init__(
        self,
        upstream_base: str,
        api_server_key: str = "",
        timeout: float = 300.0,
    ) -> None:
        self._base = upstream_base.rstrip("/")
        self._key = (api_server_key or "").strip()
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._base)

    def _upstream_headers(self, ctx: UserContext) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": build_hermes_session_id(ctx),
            "X-Hermes-Session-Key": build_gateway_session_key(ctx),
        }
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return headers

    async def chat_completions(
        self,
        ctx: UserContext,
        body: Dict[str, Any],
        *,
        stream: bool = False,
    ) -> Any:
        url = f"{self._base}/v1/chat/completions"
        headers = self._upstream_headers(ctx)
        if not stream:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                return resp.json()

        async def gen():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        return gen()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base}/health")
                return resp.status_code == 200
        except Exception:
            return False
