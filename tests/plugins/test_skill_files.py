"""Tests for DB-backed public skill asset helpers."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest


def test_normalize_skill_file_path_rejects_skill_md():
    from plugins.app_gateway.skill_files import normalize_skill_file_path

    with pytest.raises(ValueError, match="SKILL.md"):
        normalize_skill_file_path("SKILL.md")


def test_materialize_public_skill_writes_extra_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.skill_files import materialize_public_skill, public_skills_root

    materialize_public_skill(
        "demo-skill",
        "---\nname: demo-skill\ndescription: Demo.\n---\n\n# Demo\n",
        {"scripts/run.py": "print('ok')\n", "references/notes.md": "# Notes\n"},
    )
    root = public_skills_root() / "demo-skill"
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts" / "run.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert (root / "references" / "notes.md").is_file()


def test_parse_skill_zip_extracts_files():
    from plugins.app_gateway.skill_files import parse_skill_zip

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "demo-skill/SKILL.md",
            "---\nname: demo-skill\ndescription: From zip.\n---\n\n# Demo\n",
        )
        zf.writestr("demo-skill/scripts/run.py", "print('zip')\n")
    name, skill_md, files = parse_skill_zip(buf.getvalue())
    assert name == "demo-skill"
    assert "demo-skill" in skill_md
    assert files["scripts/run.py"] == "print('zip')\n"
