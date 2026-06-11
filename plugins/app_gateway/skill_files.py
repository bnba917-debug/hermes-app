"""Helpers for DB-backed public skill asset paths and disk materialization."""

from __future__ import annotations

import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Tuple

_SKILL_FILE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def normalize_skill_file_path(path: str) -> str:
    """Return a safe relative path inside a skill directory."""
    cleaned = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not cleaned:
        raise ValueError("file path is required")
    if cleaned == "SKILL.md":
        raise ValueError("use skill_md for SKILL.md; do not store it in files")
    parts = PurePosixPath(cleaned).parts
    if ".." in parts or cleaned.startswith("/"):
        raise ValueError("invalid file path")
    if not _SKILL_FILE_PATH.match(cleaned):
        raise ValueError(f"invalid file path: {cleaned}")
    return cleaned


def normalize_skill_files(files: Dict[str, str] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_path, content in (files or {}).items():
        rel = normalize_skill_file_path(raw_path)
        out[rel] = str(content or "")
    return out


def public_skills_root() -> Path:
    from plugins.app_gateway.user_scope import operator_app_gateway_root

    root = operator_app_gateway_root() / "public-skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def materialize_public_skill(
    name: str,
    skill_md: str,
    files: Dict[str, str] | None = None,
) -> Path:
    """Write one public skill tree under ``public-skills/<name>/``."""
    from plugins.app_gateway.skill_registry import _slug

    slug = _slug(name)
    root = public_skills_root() / slug
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(str(skill_md or "").strip(), encoding="utf-8")
    for rel, content in normalize_skill_files(files).items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return root


def remove_public_skill_dir(name: str) -> None:
    from plugins.app_gateway.skill_registry import _slug

    root = public_skills_root() / _slug(name)
    if root.is_dir():
        shutil.rmtree(root)


def sync_public_skills_catalog(
    skills: Iterable[Dict[str, object]],
) -> Path:
    """Materialize all active public skills and remove stale directories."""
    active: set[str] = set()
    for skill in skills:
        name = str(skill.get("name") or "")
        if not name:
            continue
        active.add(name)
        files = skill.get("files") if isinstance(skill.get("files"), dict) else {}
        materialize_public_skill(
            name,
            str(skill.get("skill_md") or ""),
            files if isinstance(files, dict) else {},
        )
    root = public_skills_root()
    for child in root.iterdir():
        if child.is_dir() and child.name not in active:
            shutil.rmtree(child)
    return root


def parse_skill_zip(data: bytes) -> Tuple[str, str, Dict[str, str]]:
    """Parse a skill ZIP into ``(name, skill_md, extra_files)``."""
    with zipfile.ZipFile(BytesIO(data)) as zf:
        entries = [n for n in zf.namelist() if not n.endswith("/")]
        if not entries:
            raise ValueError("zip archive is empty")
        skill_md_paths = [n for n in entries if n.endswith("SKILL.md")]
        if not skill_md_paths:
            raise ValueError("zip must contain SKILL.md")
        if len(skill_md_paths) > 1:
            prefixes = {str(PurePosixPath(p).parent) for p in skill_md_paths}
            if len(prefixes) > 1:
                raise ValueError("zip must contain exactly one skill directory")
        skill_md_path = skill_md_paths[0]
        prefix = PurePosixPath(skill_md_path).parent
        prefix_parts = prefix.parts if prefix != PurePosixPath(".") else ()
        skill_md = zf.read(skill_md_path).decode("utf-8")
        try:
            from agent.skill_utils import parse_frontmatter

            fm, _ = parse_frontmatter(skill_md)
            name = str(fm.get("name") or "").strip()
        except Exception:
            name = ""
        if not name:
            if prefix_parts:
                name = prefix_parts[-1]
            else:
                raise ValueError("SKILL.md frontmatter must include name")
        files: Dict[str, str] = {}
        for entry in entries:
            if entry == skill_md_path:
                continue
            rel = PurePosixPath(entry)
            if prefix_parts and rel.parts[: len(prefix_parts)] != prefix_parts:
                continue
            rel_path = "/".join(rel.parts[len(prefix_parts) :])
            if not rel_path:
                continue
            files[normalize_skill_file_path(rel_path)] = zf.read(entry).decode("utf-8")
        return name, skill_md, files


def list_skill_file_summaries(files: Dict[str, str] | None) -> List[Dict[str, object]]:
    return [
        {"path": path, "size": len(content or "")}
        for path, content in sorted((files or {}).items())
    ]
