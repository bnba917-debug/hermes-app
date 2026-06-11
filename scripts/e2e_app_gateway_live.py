#!/usr/bin/env python3
"""Live E2E smoke test against a running App Gateway (default http://127.0.0.1:8787)."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("FAIL: httpx required (pip install httpx)")
    sys.exit(2)

BASE = os.environ.get("HERMES_E2E_GATEWAY", "http://127.0.0.1:8787").rstrip("/")
DEV_CODE = os.environ.get("HERMES_E2E_SMS_CODE", "111111")
PHONE = os.environ.get("HERMES_E2E_PHONE", f"139{int(time.time()) % 10_000_0000:08d}")


class Step:
    def __init__(self) -> None:
        self.results: List[Tuple[str, bool, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.results.append((name, True, detail))
        print(f"  OK  {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        self.results.append((name, False, detail))
        print(f" FAIL {name} — {detail}")

    def summary(self) -> int:
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print(f"\nE2E summary: {passed}/{total} passed")
        for name, ok, detail in self.results:
            if not ok:
                print(f"  - {name}: {detail}")
        return 0 if passed == total else 1


def _json(resp: httpx.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"_raw": data}
    except Exception:
        return {"_text": resp.text[:500]}


def _solve_captcha(question: str) -> Optional[str]:
    q = (question or "").strip().replace("?", "").replace("=", "").strip()
    for op in ("+", "-"):
        if op in q:
            parts = [p.strip() for p in q.split(op, 1)]
            if len(parts) == 2 and parts[0].lstrip("-").isdigit() and parts[1].lstrip("-").isdigit():
                a, b = int(parts[0]), int(parts[1])
                return str(a + b if op == "+" else a - b)
    return None


def main() -> int:
    step = Step()
    print(f"Live E2E → {BASE}  phone={PHONE}")

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        # 1) Health
        r = client.get("/health")
        if r.status_code == 200 and r.json().get("status") == "ok":
            body = r.json()
            step.ok(
                "health",
                f"postgres={body.get('postgres_configured')} redis={body.get('redis')}",
            )
        else:
            step.fail("health", f"status={r.status_code} body={r.text[:200]}")
            return step.summary()

        r = client.get("/health?deep=true")
        if r.status_code == 200:
            step.ok("health_deep")
        else:
            step.fail("health_deep", f"status={r.status_code}")

        # 2) SMS captcha + send (optional)
        captcha_token = captcha_answer = None
        rc = client.get("/v1/auth/sms/captcha")
        if rc.status_code == 200:
            cbody = _json(rc)
            captcha_token = cbody.get("captcha_token")
            captcha_answer = _solve_captcha(str(cbody.get("question") or ""))
            if captcha_token and captcha_answer is not None:
                step.ok("sms_captcha", f"answer={captcha_answer}")
            else:
                step.fail("sms_captcha", str(cbody)[:200])
        else:
            step.ok("sms_captcha", "skipped (disabled or unavailable)")

        send_payload: Dict[str, Any] = {"phone": PHONE}
        if captcha_token:
            send_payload["captcha_token"] = captcha_token
            send_payload["captcha_answer"] = captcha_answer
        rs = client.post("/v1/auth/sms/send", json=send_payload)
        if rs.status_code in (200, 201):
            step.ok("sms_send")
        else:
            step.fail("sms_send", f"{rs.status_code} {_json(rs)}")

        # 3) Register
        rr = client.post(
            "/v1/auth/register",
            json={"phone": PHONE, "code": DEV_CODE, "device_id": "e2e-test"},
        )
        if rr.status_code not in (200, 201):
            rr = client.post(
                "/v1/auth/login",
                json={"phone": PHONE, "code": DEV_CODE, "device_id": "e2e-test"},
            )
        if rr.status_code not in (200, 201):
            step.fail("auth", f"{rr.status_code} {_json(rr)}")
            return step.summary()
        auth = _json(rr)
        token = str(auth.get("access_token") or "")
        if not token:
            step.fail("auth", "missing access_token")
            return step.summary()
        user_id = str(auth.get("user_id") or auth.get("sub") or "")
        headers = {"Authorization": f"Bearer {token}"}
        step.ok("auth", f"user_id={user_id or 'unknown'}")

        # 4) Onboarding status
        ro = client.get("/v1/onboarding/status", headers=headers)
        if ro.status_code != 200:
            step.fail("onboarding_status", f"{ro.status_code}")
        else:
            ob = _json(ro)
            step.ok("onboarding_status", f"complete={ob.get('complete')}")

        # 5) Sessions
        rsess = client.get("/v1/sessions", headers=headers)
        if rsess.status_code == 200:
            step.ok("sessions_list", f"count={len(_json(rsess).get('sessions') or [])}")
        else:
            step.fail("sessions_list", f"{rsess.status_code}")

        sid = f"e2e-{uuid.uuid4().hex[:8]}"
        cr = client.post("/v1/sessions", headers=headers, json={"session_id": sid})
        if cr.status_code in (200, 201):
            step.ok("sessions_create", sid)
        else:
            step.fail("sessions_create", f"{cr.status_code} {_json(cr)}")

        # 6) Skills list (before)
        sk = client.get("/v1/skills", headers=headers)
        if sk.status_code != 200:
            step.fail("skills_list", f"{sk.status_code}")
            return step.summary()
        skills_before = _json(sk).get("skills") or []
        scopes_before = {s.get("scope") for s in skills_before if isinstance(s, dict)}
        step.ok(
            "skills_list",
            f"total={len(skills_before)} scopes={sorted(scopes_before)}",
        )

        # 7) Simulate Agent skill_manage write on disk + reload
        skill_name = f"e2e-skill-{uuid.uuid4().hex[:6]}"
        wrote_disk = False
        if user_id:
            try:
                repo = Path(__file__).resolve().parents[1]
                sys.path.insert(0, str(repo))
                os.environ.setdefault("HERMES_HOME", str(Path.home() / ".hermes"))
                from plugins.app_gateway.auth import UserContext
                from plugins.app_gateway.user_scope import app_gateway_user_scope, user_hermes_home
                from tools.skill_manager_tool import _create_skill

                ctx = UserContext(
                    user_id=user_id,
                    session_id=sid,
                    device_id="e2e-test",
                    raw_claims={"sub": user_id},
                )
                content = f"""---
name: {skill_name}
description: E2E auto-created skill.
---

# E2E Skill

Created by scripts/e2e_app_gateway_live.py
"""
                with app_gateway_user_scope(ctx):
                    raw = _create_skill(skill_name, content)
                    data = raw if isinstance(raw, dict) else json.loads(raw)
                    skill_path = user_hermes_home(user_id) / "skills" / skill_name / "SKILL.md"
                    wrote_disk = data.get("success") and skill_path.is_file()
                if wrote_disk:
                    step.ok("skill_manage_disk", str(skill_path))
                else:
                    step.fail("skill_manage_disk", str(data)[:200])
            except Exception as exc:
                step.fail("skill_manage_disk", str(exc))
        else:
            step.fail("skill_manage_disk", "no user_id from auth response")

        rl = client.post("/v1/skills/reload", headers=headers)
        if rl.status_code == 200:
            step.ok("skills_reload")
        else:
            step.fail("skills_reload", f"{rl.status_code}")

        sk2 = client.get("/v1/skills", headers=headers)
        if sk2.status_code != 200:
            step.fail("skills_list_after", f"{sk2.status_code}")
        else:
            names = {
                s.get("name")
                for s in (_json(sk2).get("skills") or [])
                if isinstance(s, dict)
            }
            hit = skill_name in names
            if hit:
                scope = next(
                    s.get("scope")
                    for s in _json(sk2).get("skills") or []
                    if isinstance(s, dict) and s.get("name") == skill_name
                )
                step.ok("skills_auto_visible", f"name={skill_name} scope={scope}")
            else:
                step.fail("skills_auto_visible", f"{skill_name} not in list")

        # 8) Skills config
        sc = client.get("/v1/skills/config", headers=headers)
        if sc.status_code == 200:
            step.ok("skills_config")
        else:
            step.fail("skills_config", f"{sc.status_code}")

        # 9) Refresh token
        refresh = auth.get("refresh_token")
        if refresh:
            rf = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
            if rf.status_code == 200 and _json(rf).get("access_token"):
                step.ok("auth_refresh")
            else:
                step.fail("auth_refresh", f"{rf.status_code} {_json(rf)}")
        else:
            step.ok("auth_refresh", "skipped (no refresh_token)")

        # 10) Chat blocked or ok (onboarding may block — that's expected)
        chat_headers = {**headers, "X-Hermes-Session-Id": sid}
        chat = client.post(
            "/v1/chat/completions",
            headers=chat_headers,
            json={"messages": [{"role": "user", "content": "1+1=?"}]},
        )
        if chat.status_code == 200:
            step.ok("chat_completions", "model replied")
        elif chat.status_code in (403, 428, 503):
            step.ok("chat_completions", f"blocked as expected ({chat.status_code}) — complete onboarding for full chat E2E")
        else:
            step.fail("chat_completions", f"{chat.status_code} {_json(chat)}")

    return step.summary()


if __name__ == "__main__":
    raise SystemExit(main())
