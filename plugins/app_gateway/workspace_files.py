"""Workspace file download + tool-result path extraction for App Gateway clients."""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from plugins.app_gateway.workspace_paths import validate_workspace_relative_path


@dataclass(frozen=True)
class WorkspaceFilePayload:
    relative_path: str
    filename: str
    mime_type: str
    data: bytes
    size: int


def extract_workspace_file_paths(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    result_text: Optional[str],
) -> List[str]:
    """Return relative workspace paths produced by write_file / patch."""
    name = (tool_name or "").strip()
    paths: List[str] = []
    if name == "write_file":
        raw_path = (args or {}).get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return []
        rel = raw_path.strip()
        if result_text:
            try:
                data = json.loads(result_text)
                if isinstance(data, dict) and data.get("error"):
                    return []
            except json.JSONDecodeError:
                pass
        if validate_workspace_relative_path(rel) is None:
            paths.append(rel.replace("\\", "/"))
        return paths

    if name != "patch" or not result_text:
        return []
    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict) or not data.get("success"):
        return []
    for key in ("files_created", "files_modified"):
        items = data.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue
            rel = item.strip().replace("\\", "/")
            if validate_workspace_relative_path(rel) is None:
                paths.append(rel)
    return paths


def read_workspace_file_for_user(user_id: str, relative_path: str) -> WorkspaceFilePayload:
    """Load a file from the user's workspace (local disk or MinIO-backed cache)."""
    err = validate_workspace_relative_path(relative_path)
    if err:
        raise ValueError(err)

    from plugins.app_gateway.workspace_backend import get_workspace_backend

    backend = get_workspace_backend()
    rel = backend.normalize_relative_path(relative_path)
    data = backend.get_bytes(user_id, rel)
    if data is None:
        raise FileNotFoundError(rel)

    filename = Path(rel).name or "download"
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"
    return WorkspaceFilePayload(
        relative_path=rel,
        filename=filename,
        mime_type=mime_type,
        data=data,
        size=len(data),
    )
