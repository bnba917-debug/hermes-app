"""Minimal Python SDK — maps to tgs.html App → SDK → Gateway."""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, Iterator, List, Optional

import httpx


class HermesAppClient:
    """Client for Hermes App Gateway (/v1/chat/completions + feedback)."""

    def __init__(
        self,
        base_url: str,
        user_jwt: str,
        app_key: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_jwt = user_jwt
        self.app_key = app_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-User-Token": self.user_jwt,
        }
        if self.app_key:
            headers["X-App-Key"] = self.app_key
        return headers

    def chat(
        self,
        message: str,
        *,
        session_messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
        model: str = "hermes-agent",
    ) -> Any:
        messages: List[Dict[str, str]] = list(session_messages or [])
        messages.append({"role": "user", "content": message})
        body = {"model": model, "messages": messages, "stream": stream}
        url = f"{self.base_url}/v1/chat/completions"
        if not stream:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self._headers(), json=body)
                resp.raise_for_status()
                return resp.json()

        return self._stream_chat(url, body)

    def _stream_chat(self, url: str, body: Dict[str, Any]) -> Generator[str, None, None]:
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST", url, headers=self._headers(), json=body
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content

    def feedback(
        self,
        rating: str,
        *,
        comment: str = "",
        message_id: str = "",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/feedback"
        body = {"rating": rating, "comment": comment, "message_id": message_id}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()
