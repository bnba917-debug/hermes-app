#!/usr/bin/env python3
"""Smoke-test the three App Gateway onboarding models against live APIs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

MODELS = (
    {
        "label": "DeepSeek V4 Flash",
        "model": "deepseek-v4-flash",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
    },
    {
        "label": "Kimi K2.6",
        "model": "kimi-k2.6",
        "provider": "kimi-coding-cn",
        "base_url": "https://api.moonshot.cn/v1",
        "key_env": "KIMI_CN_API_KEY",
    },
    {
        "label": "Laguna M.1 Free (OpenRouter)",
        "model": "poolside/laguna-m.1:free",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
    },
)


def _load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            out[name.strip()] = value.strip().strip("'\"")
    for name, value in os.environ.items():
        if value.strip():
            out[name] = value.strip()
    return out


def _probe(spec: dict, api_key: str) -> tuple[bool, str]:
    try:
        from openai import OpenAI
    except ImportError:
        return False, "openai package not installed"

    client = OpenAI(api_key=api_key, base_url=spec["base_url"])
    kwargs: dict = {
        "model": spec["model"],
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "max_tokens": 16,
    }
    if spec["provider"] not in {"kimi-coding-cn", "kimi-coding"}:
        kwargs["temperature"] = 0
    try:
        resp = client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        return True, text[:80] or "(empty)"
    except Exception as exc:
        msg = str(exc).strip().replace("\n", " ")
        return False, msg[:200]


def main() -> int:
    env = _load_env()
    print("App Gateway model connectivity\n" + "=" * 40)

    ok_count = 0
    for spec in MODELS:
        key = (env.get(spec["key_env"]) or "").strip()
        if not key:
            print(f"SKIP  {spec['label']}: {spec['key_env']} not set")
            continue
        ok, detail = _probe(spec, key)
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {spec['label']} ({spec['model']})")
        print(f"      {detail}")
        if ok:
            ok_count += 1

    print("=" * 40)
    configured = sum(1 for s in MODELS if (env.get(s["key_env"]) or "").strip())
    print(f"Result: {ok_count}/{configured} configured models passed")
    return 0 if ok_count == configured and configured > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
