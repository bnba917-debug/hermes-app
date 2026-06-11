"""Voice HTTP API — STT/TTS aligned with CLI voice mode."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from plugins.app_gateway.auth import UserContext
from plugins.app_gateway.user_scope import app_gateway_user_scope


def transcribe_upload(
    ctx: UserContext,
    *,
    file_bytes: bytes,
    filename: str = "audio.wav",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Save upload and run configured STT (same chain as CLI)."""
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        with app_gateway_user_scope(ctx):
            from tools.transcription_tools import transcribe_audio

            return transcribe_audio(path, model=model)
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


def synthesize_speech(
    ctx: UserContext,
    *,
    text: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """TTS for assistant reply playback in the mobile app (``tts`` in config.yaml)."""
    with app_gateway_user_scope(ctx):
        from tools.tts_tool import text_to_speech_tool

        raw = text_to_speech_tool(text=text, output_path=output_path)
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            data = {"success": False, "error": str(raw)}
        if not isinstance(data, dict):
            data = {"success": False, "error": "unexpected TTS response"}
        return data
