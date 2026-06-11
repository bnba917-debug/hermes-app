#!/usr/bin/env python3
"""Live E2E: onboarded user chat + PG history readback + skill scope check."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

try:
    import httpx
except ImportError:
    print("FAIL: pip install httpx")
    sys.exit(2)

BASE = os.environ.get("HERMES_E2E_GATEWAY", "http://127.0.0.1:8787").rstrip("/")
PHONE = os.environ.get("HERMES_E2E_PHONE", "8613900139000")
CODE = os.environ.get("HERMES_E2E_SMS_CODE", "111111")
MODEL = os.environ.get("HERMES_E2E_MODEL", "kimi-k2.6")
PROVIDER = os.environ.get("HERMES_E2E_PROVIDER", "kimi-coding-cn")
API_KEY_ENV = os.environ.get("HERMES_E2E_API_KEY_ENV", "KIMI_CN_API_KEY")


def _load_api_key() -> str:
    key = (os.environ.get(API_KEY_ENV) or "").strip()
    if key:
        return key
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == API_KEY_ENV:
                return value.strip().strip("'\"")
    return ""


def _solve_captcha(question: str) -> str | None:
    nums = [int(x) for x in re.findall(r"-?\d+", question or "")]
    if "+" in question and len(nums) >= 2:
        return str(nums[0] + nums[1])
    if "-" in question and len(nums) >= 2:
        return str(nums[0] - nums[1])
    return None


def main() -> int:
    api_key = _load_api_key()
    if not api_key:
        print(f"FAIL: set {API_KEY_ENV} in ~/.hermes/.env or environment")
        return 2

    print(f"Onboarded chat E2E → {BASE} phone={PHONE}")

    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        cap = client.get("/v1/auth/sms/captcha").json()
        ans = _solve_captcha(str(cap.get("question") or ""))
        client.post(
            "/v1/auth/sms/send",
            json={
                "phone": PHONE,
                "captcha_token": cap["captcha_token"],
                "captcha_answer": ans,
            },
        )
        auth = client.post(
            "/v1/auth/login",
            json={"phone": PHONE, "code": CODE, "device_id": "e2e-onboarded"},
        ).json()
        token = auth["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        ob = client.get("/v1/onboarding/status", headers=headers).json()
        if not ob.get("ready_for_chat"):
            print("  completing onboarding …")
            done = client.post(
                "/v1/onboarding/complete",
                headers=headers,
                json={
                    "api_key": api_key,
                    "model": MODEL,
                    "provider": PROVIDER,
                    "api_key_env": API_KEY_ENV,
                    "base_url": "https://api.moonshot.cn/v1",
                },
            )
            if done.status_code not in (200, 201):
                print(f"FAIL onboarding_complete {done.status_code} {done.text[:300]}")
                return 1
            ob = client.get("/v1/onboarding/status", headers=headers).json()

        if not ob.get("ready_for_chat"):
            print(f"FAIL not ready_for_chat: {json.dumps(ob, ensure_ascii=False)[:400]}")
            return 1
        print(f"  OK  onboarding ready model={ob.get('inference', {}).get('model')}")

        scopes: dict[str, int] = {}
        for skill in client.get("/v1/skills", headers=headers).json().get("skills") or []:
            sc = str(skill.get("scope") or "?")
            scopes[sc] = scopes.get(sc, 0) + 1
        print(f"  OK  skill scopes {scopes}")
        if scopes.get("bundled_readonly", 0) == 0:
            print("  WARN no bundled_readonly skills in list")

        sid = f"e2e-chat-{uuid.uuid4().hex[:8]}"
        session_headers = {**headers, "X-Hermes-Session-Id": sid}
        client.post("/v1/sessions", headers=session_headers, json={"session_id": sid})

        prompt = "只回答一个阿拉伯数字，不要解释：1+1等于几？"
        chat = client.post(
            "/v1/chat/completions",
            headers=session_headers,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "use_server_history": True,
            },
        )
        if chat.status_code != 200:
            print(f"FAIL chat {chat.status_code} {chat.text[:500]}")
            return 1

        body = chat.json()
        text = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        print(f"  OK  chat reply ({len(text)} chars): {text[:120]!r}")

        hist = client.get(
            f"/v1/sessions/{sid}/messages",
            headers=session_headers,
        ).json()
        messages = hist.get("messages") or []
        roles = [m.get("role") for m in messages]
        print(f"  OK  history readback count={len(messages)} roles={roles}")

        if len(messages) < 2:
            print("FAIL history missing user/assistant pair")
            return 1

        user_msgs = [m for m in messages if m.get("role") == "user"]
        asst_msgs = [m for m in messages if m.get("role") == "assistant"]
        if not user_msgs or not asst_msgs:
            print("FAIL history roles incomplete")
            return 1

        if prompt not in (user_msgs[-1].get("content") or ""):
            print("FAIL user message not persisted")
            return 1

        print("\nOnboarded chat + history E2E: PASSED")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
