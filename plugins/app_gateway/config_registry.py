"""Hot-reloadable prompt/tool overrides (tgs.html 配置中心)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from plugins.app_gateway.user_scope import operator_app_gateway_root

logger = logging.getLogger(__name__)

_DEFAULT_REL = Path("app_gateway") / "overrides.yaml"


class ConfigRegistry:
    """Loads ``~/.hermes/app_gateway/overrides.yaml`` and reloads on mtime change."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or (operator_app_gateway_root() / "overrides.yaml")
        self._lock = threading.Lock()
        self._mtime_ns: Optional[int] = None
        self._data: Dict[str, Any] = {}

    @property
    def path(self) -> Path:
        return self._path

    def reload(self, *, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            if not self._path.is_file():
                self._data = {}
                self._mtime_ns = None
                return self._data
            try:
                st = self._path.stat()
            except OSError:
                return self._data
            if not force and self._mtime_ns == st.st_mtime_ns:
                return self._data
            try:
                raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    raw = {}
                self._data = raw
                self._mtime_ns = st.st_mtime_ns
                logger.info("Reloaded app gateway overrides from %s", self._path)
            except Exception as exc:
                logger.warning("Failed to load overrides %s: %s", self._path, exc)
            return self._data

    def get_ephemeral_system_prefix(self) -> str:
        data = self.reload()
        parts = []
        prompt = data.get("system_prompt_prefix") or data.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            parts.append(prompt.strip())
        tools_note = data.get("tools_note")
        if isinstance(tools_note, str) and tools_note.strip():
            parts.append(f"[Tool policy]\n{tools_note.strip()}")
        return "\n\n".join(parts)

    def scaffold_if_missing(self) -> Path:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_file():
            return self._path
        example = {
            "system_prompt_prefix": (
                "You are Hermes serving mobile app users. Be concise and safe."
            ),
            "tools_note": (
                "Respect per-user isolation; never reference other users' data. "
                "File tools: relative paths under workspace/ only. "
                "App gateway has no web_search or browser tools — answer from context or say you cannot browse. "
                "Skills: skills_list / skill_view when a skill applies."
            ),
        }
        self._path.write_text(
            yaml.safe_dump(example, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return self._path
