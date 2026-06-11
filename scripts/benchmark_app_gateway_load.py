#!/usr/bin/env python3
"""Load test App Gateway multi-tenant path (no real LLM calls by default).

Measures:
  - Concurrent mock chat (concurrency pool + user scope)
  - HTTP: health, auth, skills, inference status
  - Session DB writes (SQLite or PostgreSQL)

After the run, wipes storage when ``--wipe-after`` (default on).

Usage:
  python scripts/benchmark_app_gateway_load.py
  python scripts/benchmark_app_gateway_load.py --users 100 --concurrent 100
  python scripts/benchmark_app_gateway_load.py --no-wipe-after
  python scripts/benchmark_app_gateway_load.py --use-config-home
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BENCH_PHONE_PREFIX = "1990000"
BENCH_USER_PREFIX = "bench-user-"


def _pct(samples: List[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f] * 1000.0
    return (ordered[f] + (ordered[c] - ordered[f]) * (k - f)) * 1000.0


def _summarize(name: str, samples: List[float], *, extra: Optional[dict] = None) -> dict:
    if not samples:
        return {"name": name, "n": 0, **(extra or {})}
    return {
        "name": name,
        "n": len(samples),
        "ok": len(samples),
        "mean_ms": round(statistics.mean(samples) * 1000.0, 2),
        "p50_ms": round(_pct(samples, 50), 2),
        "p99_ms": round(_pct(samples, 99), 2),
        "max_ms": round(max(samples) * 1000.0, 2),
        **(extra or {}),
    }


@dataclass
class BenchConfig:
    users: int = 50
    concurrent: int = 50
    mock_chat_rounds: int = 2
    session_writes_per_user: int = 5
    max_concurrent_agents: int = 128
    agent_workers: int = 160
    jwt_secret: str = "bench-jwt-secret"
    dev_sms_code: str = "111111"
    wipe_after: bool = True
    use_config_home: bool = False
    postgres_url: str = ""


def _setup_hermes_home(cfg: BenchConfig) -> Path:
    if cfg.use_config_home:
        from hermes_constants import get_hermes_home

        return get_hermes_home()

    tmp = Path(tempfile.mkdtemp(prefix="hermes-bench-"))
    home = tmp / ".hermes"
    home.mkdir(parents=True)
    os.environ["HERMES_HOME"] = str(home)

    import yaml

    storage: dict = {"session_backend": "sqlite"}
    if cfg.postgres_url:
        storage = {
            "session_backend": "postgres",
            "postgres_url": cfg.postgres_url,
            "postgres_pool_size": 32,
            "kanban_backend": "postgres",
            "cron_backend": "postgres",
        }
        os.environ["HERMES_STORAGE_POSTGRES_URL"] = cfg.postgres_url

    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "_config_version": 1,
                "storage": storage,
                "app_gateway": {
                    "enabled": True,
                    "jwt_secret": cfg.jwt_secret,
                    "auth_mode": "dev",
                    "dev_sms_code": cfg.dev_sms_code,
                    "max_concurrent_agents": cfg.max_concurrent_agents,
                    "agent_executor_workers": cfg.agent_workers,
                    "per_user_skills_isolated": True,
                    "per_user_api_keys": True,
                    "require_onboarding_before_chat": False,
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return home


def _make_gateway_config(cfg: BenchConfig) -> Any:
    from plugins.app_gateway.config import AppGatewayConfig

    return AppGatewayConfig(
        enabled=True,
        jwt_secret=cfg.jwt_secret,
        require_jwt=True,
        auth_mode="dev",
        dev_sms_code=cfg.dev_sms_code,
        max_concurrent_agents=cfg.max_concurrent_agents,
        agent_executor_workers=cfg.agent_workers,
        per_user_skills_isolated=True,
        per_user_api_keys=True,
        require_onboarding_before_chat=False,
        postgres_url=cfg.postgres_url,
        rate_limit_rpm=100_000,
    )


def _register_users(n: int, cfg: BenchConfig) -> List[dict]:
    from plugins.app_gateway.phone_auth import normalize_phone, verify_phone_login

    gw = _make_gateway_config(cfg)
    users: List[dict] = []
    for i in range(n):
        phone = normalize_phone(f"{BENCH_PHONE_PREFIX}{i:04d}")
        record, token, _is_new = verify_phone_login(
            gw,
            phone=phone,
            code=cfg.dev_sms_code,
            device_id=f"bench-{i}",
        )
        users.append(
            {
                "user_id": record.user_id,
                "phone": phone,
                "token": token,
            }
        )
    return users


def _onboard_user(token: str, cfg: BenchConfig) -> None:
    from plugins.app_gateway.auth import extract_user_context, verify_hs256_jwt
    from plugins.app_gateway.onboarding import complete_onboarding

    secret = cfg.jwt_secret
    claims = verify_hs256_jwt(token, secret)
    ctx = extract_user_context(claims)
    complete_onboarding(
        ctx,
        api_key="sk-bench-fake-key",
        model="test/model",
        provider="openrouter",
    )


def _jwt_from_config() -> str:
    from plugins.app_gateway.config import load_app_gateway_config

    return load_app_gateway_config().jwt_secret or "bench-jwt-secret"


async def _bench_concurrency_pool(users: List[dict], cfg: BenchConfig) -> dict:
    from plugins.app_gateway.auth import UserContext, extract_user_context, verify_hs256_jwt
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.runtime import AppAgentRuntime

    gw_cfg = _make_gateway_config(cfg)
    runtime = AppAgentRuntime(gw_cfg)

    async def mock_run_chat(ctx, user_message, **kwargs):
        await asyncio.sleep(0.02)
        return (
            {
                "final_response": "bench-ok",
                "messages": [],
                "session_id": f"bench-{ctx.user_id}",
                "user_id": ctx.user_id,
            },
            {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )

    runtime.run_chat = mock_run_chat  # type: ignore[method-assign]

    samples: List[float] = []
    errors = 0
    secret = gw_cfg.jwt_secret

    async def one(user: dict) -> None:
        nonlocal errors
        claims = verify_hs256_jwt(user["token"], secret)
        ctx = extract_user_context(claims)
        t0 = time.perf_counter()
        try:
            for _ in range(cfg.mock_chat_rounds):
                await runtime.run_chat(ctx, "ping benchmark")
            samples.append(time.perf_counter() - t0)
        except Exception:
            errors += 1

    sem = asyncio.Semaphore(cfg.concurrent)

    async def guarded(user: dict) -> None:
        async with sem:
            await one(user)

    t_start = time.perf_counter()
    await asyncio.gather(*[guarded(u) for u in users])
    elapsed = time.perf_counter() - t_start
    stats = runtime._pool.stats()
    return {
        **_summarize("mock_chat_pool", samples),
        "errors": errors,
        "wall_s": round(elapsed, 2),
        "throughput_rps": round(len(samples) * cfg.mock_chat_rounds / max(elapsed, 0.001), 2),
        "pool": {
            "active": stats.active,
            "max": stats.max_concurrent,
            "total_started": stats.total_started,
            "total_rejected": stats.total_rejected,
        },
    }


def _bench_session_writes(users: List[dict], cfg: BenchConfig) -> dict:
    from hermes_state import get_shared_session_db

    db = get_shared_session_db()
    samples: List[float] = []

    def write_one(user: dict) -> None:
        sid = f"bench-sess-{user['user_id']}-{uuid.uuid4().hex[:8]}"
        db.create_session(sid, "app_gateway")
        t0 = time.perf_counter()
        for i in range(cfg.session_writes_per_user):
            db.append_message(
                sid,
                role="user" if i % 2 == 0 else "assistant",
                content=f"bench message {i} for {user['user_id']}",
            )
        samples.append(time.perf_counter() - t0)

    with ThreadPoolExecutor(max_workers=min(cfg.concurrent, 64)) as pool:
        futs = [pool.submit(write_one, u) for u in users]
        for fut in as_completed(futs):
            fut.result()

    backend, dsn = __import__(
        "agent.session_storage.config", fromlist=["resolve_session_backend"]
    ).resolve_session_backend()
    return {**_summarize("session_db_writes", samples), "backend": backend}


def _bench_http(users: List[dict], cfg: BenchConfig) -> dict:
    try:
        from starlette.testclient import TestClient
    except ImportError:
        return {"name": "http", "skipped": "starlette not installed"}

    from plugins.app_gateway.server import create_app

    app = create_app(_make_gateway_config(cfg))
    client = TestClient(app)
    samples_health: List[float] = []
    samples_skills: List[float] = []
    errors = 0

    def hit(user: dict) -> None:
        nonlocal errors
        headers = {"Authorization": f"Bearer {user['token']}"}
        t0 = time.perf_counter()
        try:
            r = client.get("/health")
            if r.status_code != 200:
                errors += 1
            samples_health.append(time.perf_counter() - t0)

            t1 = time.perf_counter()
            r2 = client.get("/v1/skills", headers=headers)
            if r2.status_code != 200:
                errors += 1
            samples_skills.append(time.perf_counter() - t1)
        except Exception:
            errors += 1

    with ThreadPoolExecutor(max_workers=min(cfg.concurrent, 64)) as pool:
        futs = [pool.submit(hit, u) for u in users]
        for fut in as_completed(futs):
            fut.result()

    return {
        "health": _summarize("http_health", samples_health),
        "skills_list": _summarize("http_skills_list", samples_skills),
        "errors": errors,
    }


def run_benchmark(cfg: BenchConfig) -> dict:
    os.environ["APP_GATEWAY_JWT_SECRET"] = cfg.jwt_secret
    home = _setup_hermes_home(cfg)
    t0 = time.perf_counter()

    print(f"HERMES_HOME={home}")
    backend, dsn = __import__(
        "agent.session_storage.config", fromlist=["resolve_session_backend"]
    ).resolve_session_backend()
    print(f"session_backend={backend} dsn={'set' if dsn else 'none'}")

    print(f"Registering {cfg.users} users...")
    users = _register_users(cfg.users, cfg)
    for u in users[: min(10, len(users))]:
        try:
            _onboard_user(u["token"], cfg)
        except Exception:
            pass

    report: Dict[str, Any] = {
        "users": cfg.users,
        "concurrent": cfg.concurrent,
        "max_concurrent_agents": cfg.max_concurrent_agents,
    }

    print("Benchmark: session DB writes...")
    report["session_writes"] = _bench_session_writes(users, cfg)

    print("Benchmark: HTTP endpoints...")
    report["http"] = _bench_http(users, cfg)

    print(f"Benchmark: mock chat pool ({cfg.concurrent} concurrent)...")
    report["mock_chat"] = asyncio.run(_bench_concurrency_pool(users, cfg))

    report["total_wall_s"] = round(time.perf_counter() - t0, 2)
    report["hermes_home"] = str(home)
    return report


def _wipe(cfg: BenchConfig, home: Path) -> None:
    import subprocess

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "wipe_hermes_storage.py"),
        "--confirm",
        "wipe-all",
    ]
    if cfg.postgres_url:
        cmd.extend(["--postgres-url", cfg.postgres_url])
    if not cfg.use_config_home:
        cmd.extend(["--hermes-home", str(home)])
    else:
        cmd.extend(["--hermes-home", str(home)])

    print("Wiping all storage...")
    subprocess.run(cmd, check=False)

    if not cfg.use_config_home and home.parent.name.startswith("hermes-bench"):
        shutil.rmtree(home.parent, ignore_errors=True)
        print(f"Removed temp dir {home.parent}")


def main() -> int:
    parser = argparse.ArgumentParser(description="App Gateway load benchmark")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--concurrent", type=int, default=50)
    parser.add_argument("--mock-chat-rounds", type=int, default=2)
    parser.add_argument("--session-writes", type=int, default=5)
    parser.add_argument("--max-concurrent-agents", type=int, default=128)
    parser.add_argument("--postgres-url", default="")
    parser.add_argument("--use-config-home", action="store_true", help="Use real ~/.hermes")
    parser.add_argument("--no-wipe-after", action="store_true")
    args = parser.parse_args()

    pg = (args.postgres_url or "").strip()
    if not pg:
        pg = os.environ.get("HERMES_STORAGE_POSTGRES_URL", "").strip()
    if not pg and args.use_config_home:
        try:
            from agent.session_storage.config import resolve_postgres_url

            pg = resolve_postgres_url()
        except Exception:
            pg = ""

    cfg = BenchConfig(
        users=args.users,
        concurrent=args.concurrent,
        mock_chat_rounds=args.mock_chat_rounds,
        session_writes_per_user=args.session_writes,
        max_concurrent_agents=args.max_concurrent_agents,
        wipe_after=not args.no_wipe_after,
        use_config_home=args.use_config_home,
        postgres_url=pg,
    )

    report = run_benchmark(cfg)
    print("\n=== Benchmark report ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    home = Path(report["hermes_home"])
    if cfg.wipe_after:
        _wipe(cfg, home)
    else:
        print("Skipped wipe (--no-wipe-after)")

    rejected = report.get("mock_chat", {}).get("pool", {}).get("total_rejected", 0)
    if rejected:
        print(f"WARNING: {rejected} requests rejected by concurrency pool", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
