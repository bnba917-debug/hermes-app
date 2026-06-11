"""Enforce per-user workspace sandbox for App Gateway file tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

WORKSPACE_TOOLS_NOTE = (
    "File tools: use only relative paths under your workspace (e.g. `notes/todo.md`). "
    "Absolute paths and `..` are rejected."
)


def _app_gateway_platform_active() -> bool:
    try:
        from gateway.session_context import get_session_env

        return get_session_env("HERMES_SESSION_PLATFORM") == "app_gateway"
    except Exception:
        return False


def validate_workspace_relative_path(filepath: str) -> Optional[str]:
    """Return an error message if *filepath* must be rejected before resolve."""
    raw = (filepath or "").strip()
    if not raw:
        return "path is required"
    p = Path(raw)
    if p.is_absolute() or os.path.isabs(raw):
        return (
            "Absolute paths are blocked in App Gateway. "
            "Use a relative path under your workspace (e.g. notes/todo.md)."
        )
    if ".." in p.parts:
        return "Path must stay within workspace (no '..')."
    return None


def workspace_base_for_task(task_id: str = "default") -> Path:
    """Resolved workspace root (terminal cwd ContextVar or live terminal cwd)."""
    from tools.file_tools import _get_live_tracking_cwd

    from gateway.session_context import get_terminal_cwd

    base = _get_live_tracking_cwd(task_id) or get_terminal_cwd()
    return Path(base).expanduser().resolve()


def enforce_resolved_within_workspace(
    resolved: Path,
    *,
    task_id: str = "default",
) -> Tuple[Optional[Path], Optional[str]]:
    """Ensure *resolved* stays under the task workspace base."""
    base = workspace_base_for_task(task_id)
    try:
        resolved.resolve().relative_to(base)
    except ValueError:
        return None, (
            f"Path escapes workspace: {resolved}\n"
            f"Workspace root: {base}\n"
            "Use a relative path under your workspace directory."
        )
    return resolved, None


def resolve_app_gateway_path(filepath: str, task_id: str = "default") -> Tuple[Optional[Path], Optional[str]]:
    """Validate, resolve relative to workspace, and confine to workspace."""
    err = validate_workspace_relative_path(filepath)
    if err:
        return None, err
    base = workspace_base_for_task(task_id)
    resolved = (base / filepath).resolve()
    return enforce_resolved_within_workspace(resolved, task_id=task_id)
