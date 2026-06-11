"""Track in-flight app-gateway agent runs for stop / SSE events."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class ActiveRun:
    run_id: str
    user_id: str
    session_id: str
    agent: Any = None
    created_at: float = field(default_factory=time.time)


_lock = threading.Lock()
_runs: Dict[str, ActiveRun] = {}


def register_run(
    run_id: str,
    *,
    user_id: str,
    session_id: str,
    agent: Any = None,
) -> None:
    with _lock:
        _runs[run_id] = ActiveRun(
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            agent=agent,
        )


def attach_agent(run_id: str, agent: Any) -> None:
    with _lock:
        entry = _runs.get(run_id)
        if entry is not None:
            entry.agent = agent


def pop_run(run_id: str) -> None:
    with _lock:
        _runs.pop(run_id, None)


def active_run_count(user_id: str) -> int:
    """In-process runs still registered for *user_id*."""
    with _lock:
        return sum(1 for entry in _runs.values() if entry.user_id == user_id)


def cancel_runs_for_user(user_id: str) -> int:
    """Interrupt all active runs for *user_id* (account deletion)."""
    with _lock:
        targets = [
            (rid, entry.agent)
            for rid, entry in list(_runs.items())
            if entry.user_id == user_id
        ]
    stopped = 0
    for run_id, agent in targets:
        if agent is not None:
            try:
                agent.interrupt()
                stopped += 1
            except Exception:
                pass
        pop_run(run_id)
    return stopped


def stop_run(run_id: str, user_id: str) -> bool:
    with _lock:
        entry = _runs.get(run_id)
        if entry is None or entry.user_id != user_id:
            return False
        agent = entry.agent
    if agent is None:
        return False
    try:
        agent.interrupt()
        return True
    except Exception:
        return False


def resolve_approval(
    run_id: str,
    user_id: str,
    choice: str,
    *,
    gateway_session_key: str,
) -> bool:
    with _lock:
        entry = _runs.get(run_id)
        if entry is None or entry.user_id != user_id:
            return False
    try:
        from tools.approval import resolve_gateway_approval

        return resolve_gateway_approval(gateway_session_key, choice)
    except Exception:
        return False
