#!/usr/bin/env python3
"""Compare SQLite vs PostgreSQL storage hot paths (sessions, kanban, cron).

Usage:
  python scripts/benchmark_storage_backends.py --backend sqlite
  python scripts/benchmark_storage_backends.py --backend postgres --postgres-url postgresql://...
  python scripts/benchmark_storage_backends.py --compare  # both if PG URL configured

Does not call LLM APIs — only local I/O.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f] * 1000.0
    return (ordered[f] + (ordered[c] - ordered[f]) * (k - f)) * 1000.0


def _bench(name: str, fn, *, iterations: int, warmup: int = 3) -> dict:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    total_ms = sum(samples) * 1000.0
    return {
        "op": name,
        "n": iterations,
        "total_ms": round(total_ms, 2),
        "mean_ms": round(statistics.mean(samples) * 1000.0, 3),
        "p50_ms": round(_percentile(samples, 50), 3),
        "p99_ms": round(_percentile(samples, 99), 3),
    }


def _setup_env(backend: str, postgres_url: str | None, tmp_home: Path) -> None:
    os.environ["HERMES_HOME"] = str(tmp_home)
    cfg_path = tmp_home / "config.yaml"
    storage = {"session_backend": backend, "kanban_backend": backend, "cron_backend": backend}
    if postgres_url:
        storage["postgres_url"] = postgres_url
    import yaml

    cfg_path.write_text(
        yaml.safe_dump({"storage": storage, "_config_version": 1}, default_flow_style=False),
        encoding="utf-8",
    )
    if backend == "postgres" and postgres_url:
        os.environ["HERMES_STORAGE_POSTGRES_URL"] = postgres_url


def _bench_sessions(iterations: int) -> list[dict]:
    from hermes_state import get_shared_session_db

    db = get_shared_session_db()
    sid = f"bench-{uuid.uuid4().hex[:12]}"
    db.create_session(sid, "benchmark")

    def append():
        db.append_message(sid, "user", f"msg-{uuid.uuid4().hex[:8]}")

    def read_conv():
        db.get_messages_as_conversation(sid)

    def search():
        db.search_messages("bench msg", limit=10)

    out = [
        _bench("session.append_message", append, iterations=iterations),
        _bench("session.get_messages_as_conversation", read_conv, iterations=iterations),
    ]
    try:
        out.append(_bench("session.search_messages", search, iterations=max(5, iterations // 2)))
    except Exception as exc:
        out.append({"op": "session.search_messages", "error": str(exc)})
    return out


def _bench_kanban_on_conn(conn, *, iterations: int) -> list[dict]:
    def count_ready():
        conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'ready'").fetchone()

    return [_bench("kanban.count_ready", count_ready, iterations=iterations)]


def _bench_cron(iterations: int) -> list[dict]:
    from cron.jobs import load_jobs

    return [_bench("cron.load_jobs", load_jobs, iterations=iterations)]


def _bench_gateway_kit(iterations: int) -> list[dict]:
    """Config/toolset cache only (no LLM credential resolution)."""
    from gateway.runtime_cache import get_gateway_agent_kit, invalidate_gateway_agent_kit

    def cold():
        invalidate_gateway_agent_kit()
        get_gateway_agent_kit(platform="api_server")

    def warm():
        get_gateway_agent_kit(platform="api_server")

    try:
        return [
            _bench(
                "gateway.agent_kit_cold",
                cold,
                iterations=max(3, iterations // 5),
                warmup=0,
            ),
            _bench("gateway.agent_kit_warm", warm, iterations=iterations),
        ]
    except Exception as exc:
        return [{"op": "gateway.agent_kit", "error": str(exc)}]


def run_suite(backend: str, postgres_url: str | None, *, iterations: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="hermes-bench-") as td:
        tmp_home = Path(td) / ".hermes"
        tmp_home.mkdir(parents=True)
        _setup_env(backend, postgres_url, tmp_home)

        # Force re-resolve backends after env change.
        import importlib
        import agent.session_storage.config as scfg

        importlib.reload(scfg)

        from gateway.runtime_cache import invalidate_gateway_agent_kit

        invalidate_gateway_agent_kit()

        results: list[dict] = []
        kanban_conn = None
        try:
            results.extend(_bench_sessions(iterations))
            from hermes_cli import kanban_db

            board = os.environ.get("HERMES_KANBAN_BOARD", "default")
            try:
                kanban_conn = kanban_db.connect(board=board)
                results.extend(
                    _bench_kanban_on_conn(kanban_conn, iterations=iterations),
                )
            except Exception as exc:
                results.append({"op": "kanban.count_ready", "error": str(exc)})
            results.extend(_bench_cron(iterations))
            results.extend(_bench_gateway_kit(iterations))
        except Exception as exc:
            return {"backend": backend, "error": str(exc), "results": results}
        finally:
            if kanban_conn is not None and hasattr(kanban_conn, "close"):
                try:
                    kanban_conn.close()
                except Exception:
                    pass
            try:
                from hermes_state import reset_shared_session_stores

                reset_shared_session_stores()
            except Exception:
                pass
            try:
                from gateway.runtime_cache import invalidate_gateway_agent_kit

                invalidate_gateway_agent_kit()
            except Exception:
                pass

        return {"backend": backend, "hermes_home": str(tmp_home), "results": results}


def _print_table(rows: list[dict]) -> None:
    backends = [r["backend"] for r in rows if "error" not in r]
    if not backends:
        for r in rows:
            print(f"\n=== {r.get('backend', '?')} ERROR ===\n{r.get('error')}")
        return

    ops: list[str] = []
    for r in rows:
        if "error" in r:
            continue
        for item in r["results"]:
            if item.get("op") and item["op"] not in ops:
                ops.append(item["op"])

    hdr = f"{'operation':<40}" + "".join(f"{b:>18}" for b in backends)
    print(hdr)
    print("-" * len(hdr))
    for op in ops:
        line = f"{op:<40}"
        for r in rows:
            if "error" in r:
                line += f"{'ERR':>18}"
                continue
            cell = next((x for x in r["results"] if x.get("op") == op), None)
            if cell is None:
                line += f"{'—':>18}"
            elif "error" in cell:
                line += f"{'fail':>18}"
            else:
                line += f"{cell['p50_ms']:>14.3f} ms"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("sqlite", "postgres", "auto"),
        default="auto",
        help="Force session/kanban/cron backend (auto = run compare if PG URL set)",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.environ.get("HERMES_STORAGE_POSTGRES_URL", ""),
        help="PostgreSQL DSN (required for postgres / compare)",
    )
    parser.add_argument("-n", "--iterations", type=int, default=50)
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run sqlite and postgres side-by-side",
    )
    args = parser.parse_args()

    compare = args.compare or args.backend == "auto"
    pg_url = (args.postgres_url or "").strip()

    suites: list[dict] = []
    if compare:
        if not pg_url:
            print("No --postgres-url / HERMES_STORAGE_POSTGRES_URL; running sqlite only.")
            suites.append(run_suite("sqlite", None, iterations=args.iterations))
        else:
            for backend, url in (("sqlite", None), ("postgres", pg_url)):
                suites.append(run_suite(backend, url, iterations=args.iterations))
                try:
                    from hermes_state import reset_shared_session_stores

                    reset_shared_session_stores()
                except Exception:
                    pass
    else:
        backend = "sqlite" if args.backend == "sqlite" else "postgres"
        if backend == "postgres" and not pg_url:
            print("postgres backend requires --postgres-url", file=sys.stderr)
            return 2
        suites.append(
            run_suite(backend, pg_url if backend == "postgres" else None, iterations=args.iterations)
        )

    for s in suites:
        print(f"\n=== {s['backend'].upper()} ===")
        if "error" in s:
            print(f"ERROR: {s['error']}")
            continue
        for item in s["results"]:
            if "error" in item:
                print(f"  {item.get('op', '?')}: ERROR {item['error']}")
            else:
                print(
                    f"  {item['op']}: n={item['n']} "
                    f"mean={item['mean_ms']}ms p50={item['p50_ms']}ms p99={item['p99_ms']}ms"
                )

    if len(suites) > 1:
        print("\n--- P50 comparison ---")
        _print_table(suites)

    return 0 if all("error" not in s for s in suites) else 1


if __name__ == "__main__":
    raise SystemExit(main())
