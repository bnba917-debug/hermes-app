"""Multimodal chat message parsing for App Gateway."""

from __future__ import annotations

from plugins.app_gateway.chat_messages import parse_chat_completions_messages


def test_parse_text_only():
    parsed = parse_chat_completions_messages(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
    )
    assert parsed.error_message is None
    assert parsed.system_prompt == "You are helpful."
    assert parsed.user_message == "Hello"
    assert parsed.history == []


def test_parse_multimodal_image_url():
    parsed = parse_chat_completions_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/a.png"},
                    },
                ],
            }
        ]
    )
    assert parsed.error_message is None
    assert isinstance(parsed.user_message, list)
    assert len(parsed.user_message) == 2
    assert parsed.user_message[0]["type"] == "text"


def test_parse_rejects_unsupported_file_part():
    parsed = parse_chat_completions_messages(
        [
            {
                "role": "user",
                "content": [{"type": "file", "file_id": "abc"}],
            }
        ]
    )
    assert parsed.error_code == "unsupported_content_type"
