"""OpenAI Chat Completions message parsing (shared with api_server)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from gateway.platforms.api_server import (
    _content_has_visible_payload,
    _normalize_chat_content,
    _normalize_multimodal_content,
)


@dataclass
class ParsedChatMessages:
    system_prompt: Optional[str]
    user_message: Any
    history: List[Dict[str, Any]]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_param: Optional[str] = None


def parse_chat_completions_messages(messages: List[Dict[str, Any]]) -> ParsedChatMessages:
    """Parse ``messages`` like gateway api_server (text + vision multimodal)."""
    if not messages or not isinstance(messages, list):
        return ParsedChatMessages(
            system_prompt=None,
            user_message="",
            history=[],
            error_code="invalid_request_error",
            error_message="Missing or invalid 'messages' field",
            error_param="messages",
        )

    system_prompt: Optional[str] = None
    conversation: List[Dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        raw_content = msg.get("content", "")

        if role == "system":
            content = _normalize_chat_content(raw_content)
            if system_prompt is None:
                system_prompt = content
            elif content:
                system_prompt = f"{system_prompt}\n{content}"
            continue

        if role in ("user", "assistant"):
            try:
                content = _normalize_multimodal_content(raw_content)
            except ValueError as exc:
                raw_err = str(exc)
                code, _, message = raw_err.partition(":")
                if not message:
                    code, message = "invalid_content_part", raw_err
                return ParsedChatMessages(
                    system_prompt=system_prompt,
                    user_message="",
                    history=[],
                    error_code=code,
                    error_message=message,
                    error_param=f"messages[{idx}].content",
                )
            conversation.append({"role": role, "content": content})

    user_message: Any = ""
    history: List[Dict[str, Any]] = []
    if conversation:
        user_message = conversation[-1].get("content", "")
        history = conversation[:-1]

    if not _content_has_visible_payload(user_message):
        return ParsedChatMessages(
            system_prompt=system_prompt,
            user_message="",
            history=history,
            error_code="invalid_request_error",
            error_message="No user message found in messages",
            error_param="messages",
        )

    return ParsedChatMessages(
        system_prompt=system_prompt,
        user_message=user_message,
        history=history,
    )


def openai_error_body(
    message: str,
    *,
    code: str = "invalid_request_error",
    param: Optional[str] = None,
) -> Dict[str, Any]:
    err: Dict[str, Any] = {"message": message, "type": code}
    if param:
        err["param"] = param
    return {"error": err}
