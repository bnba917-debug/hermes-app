"""PostgreSQL-backed App Gateway skill registry.

Public skills are managed by the standalone ``plugins.app_admin`` service and
read by the app gateway from the same PostgreSQL database. Per-user DB-backed
private skills are not supported — users rely on bundled/public skills only.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

_VALID_VISIBILITY = {"public", "private"}
_VALID_STATUS = {"active", "disabled", "deleted"}


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name or "").strip()).strip("-")
    if not cleaned:
        raise ValueError("skill name is required")
    return cleaned[:128]


def _description_from_skill_md(skill_md: str) -> str:
    try:
        from agent.skill_utils import parse_frontmatter

        fm, _ = parse_frontmatter(skill_md or "")
        return str(fm.get("description") or "").strip()
    except Exception:
        return ""


def _row_to_dict(
    row: Dict[str, Any],
    *,
    include_body: bool = False,
    files: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "visibility": row["visibility"],
        "owner_user_id": row["owner_user_id"],
        "status": row["status"],
        "description": row["description"] or "",
        "version": int(row["version"] or 1),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }
    if include_body:
        data["skill_md"] = row["skill_md"] or ""
    if files is not None:
        data["files"] = files
    return data


class SkillRegistry:
    """Persistent registry for DB-backed App Gateway skills."""

    def __init__(self, dsn: str) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise RuntimeError("PostgreSQL DSN is required for App Gateway skill registry")
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL skill registry requires psycopg. "
                "Install: uv pip install -e '.[postgres]'"
            ) from exc
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS hermes_app_skills (
                            id BIGSERIAL PRIMARY KEY,
                            name TEXT NOT NULL,
                            visibility TEXT NOT NULL CHECK (visibility IN ('public', 'private')),
                            owner_user_id TEXT,
                            status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'deleted')),
                            description TEXT NOT NULL DEFAULT '',
                            skill_md TEXT NOT NULL,
                            version INTEGER NOT NULL DEFAULT 1,
                            created_at DOUBLE PRECISION NOT NULL,
                            updated_at DOUBLE PRECISION NOT NULL,
                            UNIQUE NULLS NOT DISTINCT (name, visibility, owner_user_id)
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_hermes_app_skills_visible
                        ON hermes_app_skills (visibility, status, name)
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS hermes_app_skill_files (
                            id BIGSERIAL PRIMARY KEY,
                            skill_id BIGINT NOT NULL REFERENCES hermes_app_skills(id) ON DELETE CASCADE,
                            relative_path TEXT NOT NULL,
                            content TEXT NOT NULL,
                            updated_at DOUBLE PRECISION NOT NULL,
                            UNIQUE (skill_id, relative_path)
                        )
                        """
                    )
                conn.commit()

    def _fetch_skill_files(self, cur, skill_id: int) -> Dict[str, str]:
        cur.execute(
            """
            SELECT relative_path, content
            FROM hermes_app_skill_files
            WHERE skill_id = %s
            ORDER BY relative_path
            """,
            (skill_id,),
        )
        return {row["relative_path"]: row["content"] for row in cur.fetchall()}

    def _replace_skill_files(
        self,
        cur,
        skill_id: int,
        files: Optional[Dict[str, str]],
        *,
        now: float,
    ) -> Dict[str, str]:
        from plugins.app_gateway.skill_files import normalize_skill_files

        normalized = normalize_skill_files(files)
        cur.execute("DELETE FROM hermes_app_skill_files WHERE skill_id = %s", (skill_id,))
        for rel, content in normalized.items():
            cur.execute(
                """
                INSERT INTO hermes_app_skill_files
                    (skill_id, relative_path, content, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (skill_id, rel, content, now),
            )
        return normalized

    def upsert_skill(
        self,
        *,
        name: str,
        skill_md: str,
        visibility: str = "public",
        owner_user_id: Optional[str] = None,
        status: str = "active",
        description: Optional[str] = None,
        files: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        name = _slug(name)
        visibility = str(visibility or "public").strip().lower()
        status = str(status or "active").strip().lower()
        if visibility not in _VALID_VISIBILITY:
            raise ValueError("visibility must be public or private")
        if visibility == "private":
            raise ValueError("private skills are not supported; use app_admin for public skills")
        if status not in _VALID_STATUS:
            raise ValueError("status must be active, disabled, or deleted")
        owner = None
        body = str(skill_md or "").strip()
        if not body:
            raise ValueError("skill_md is required")
        desc = (description if description is not None else _description_from_skill_md(body)) or ""
        now = time.time()

        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM hermes_app_skills
                        WHERE name = %s AND visibility = %s AND owner_user_id IS NOT DISTINCT FROM %s
                        """,
                        (name, visibility, owner),
                    )
                    existing = cur.fetchone()
                    if existing:
                        version = int(existing["version"] or 1) + 1
                        cur.execute(
                            """
                            UPDATE hermes_app_skills
                            SET status = %s, description = %s, skill_md = %s,
                                version = %s, updated_at = %s
                            WHERE id = %s
                            """,
                            (status, str(desc), body, version, now, existing["id"]),
                        )
                        row_id = existing["id"]
                    else:
                        version = 1
                        cur.execute(
                            """
                            INSERT INTO hermes_app_skills
                                (name, visibility, owner_user_id, status, description,
                                 skill_md, version, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                name,
                                visibility,
                                owner,
                                status,
                                str(desc),
                                body,
                                version,
                                now,
                                now,
                            ),
                        )
                        row_id = cur.fetchone()["id"]
                    cur.execute(
                        "SELECT * FROM hermes_app_skills WHERE id = %s",
                        (row_id,),
                    )
                    row = cur.fetchone()
                    if files is not None:
                        saved_files = self._replace_skill_files(cur, row_id, files, now=now)
                    else:
                        saved_files = self._fetch_skill_files(cur, int(row_id))
                conn.commit()
        from plugins.app_gateway.skill_files import materialize_public_skill

        if visibility == "public" and status == "active":
            materialize_public_skill(name, body, saved_files)
        elif visibility == "public":
            from plugins.app_gateway.skill_files import remove_public_skill_dir

            remove_public_skill_dir(name)
        return _row_to_dict(row, include_body=True, files=saved_files)

    def list_skills(
        self,
        *,
        visibility: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        include_disabled: bool = False,
        include_body: bool = False,
        include_files: bool = False,
    ) -> List[Dict[str, Any]]:
        where: List[str] = []
        params: List[Any] = []
        if visibility:
            where.append("visibility = %s")
            params.append(str(visibility).strip().lower())
        if owner_user_id is not None:
            where.append("owner_user_id = %s")
            params.append(str(owner_user_id))
        if not include_disabled:
            where.append("status = 'active'")
        sql = "SELECT * FROM hermes_app_skills"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY lower(name)"
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    out: List[Dict[str, Any]] = []
                    for row in rows:
                        files = None
                        if include_files:
                            files = self._fetch_skill_files(cur, int(row["id"]))
                        out.append(
                            _row_to_dict(
                                row,
                                include_body=include_body,
                                files=files if include_files else None,
                            )
                        )
                return out

    def get_skill(
        self,
        name: str,
        *,
        visibility: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        include_disabled: bool = False,
        include_files: bool = True,
    ) -> Optional[Dict[str, Any]]:
        name = _slug(name)
        where = ["name = %s"]
        params: List[Any] = [name]
        if visibility:
            where.append("visibility = %s")
            params.append(str(visibility).strip().lower())
        if owner_user_id is not None:
            where.append("owner_user_id = %s")
            params.append(str(owner_user_id))
        if not include_disabled:
            where.append("status = 'active'")
        sql = "SELECT * FROM hermes_app_skills WHERE " + " AND ".join(where)
        sql += " LIMIT 1"
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
                    if not row:
                        return None
                    files = self._fetch_skill_files(cur, int(row["id"])) if include_files else None
                return _row_to_dict(row, include_body=True, files=files)

    def delete_skill(
        self,
        name: str,
        *,
        visibility: str = "public",
        owner_user_id: Optional[str] = None,
    ) -> bool:
        name = _slug(name)
        owner = None if visibility == "public" else str(owner_user_id or "").strip()
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM hermes_app_skills
                        WHERE name = %s AND visibility = %s AND owner_user_id IS NOT DISTINCT FROM %s
                        """,
                        (name, visibility, owner),
                    )
                    deleted = cur.rowcount > 0
                conn.commit()
        if deleted and visibility == "public":
            from plugins.app_gateway.skill_files import remove_public_skill_dir

            remove_public_skill_dir(name)
        return deleted


def get_skill_registry() -> SkillRegistry:
    from plugins.app_gateway.config import load_app_gateway_config

    cfg = load_app_gateway_config()
    return SkillRegistry(cfg.postgres_url)
