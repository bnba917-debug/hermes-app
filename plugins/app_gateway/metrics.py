"""Lightweight Prometheus text metrics (no external dependency)."""

from __future__ import annotations

import re
import threading
from typing import Dict, Optional, Tuple

_lock = threading.Lock()
_counters: Dict[str, float] = {}
_gauges: Dict[str, float] = {}
_counter_types: Dict[str, str] = {}
_gauge_types: Dict[str, str] = {}


def _metric_key(name: str, labels: Optional[Dict[str, str]] = None) -> str:
    if not labels:
        return name
    parts = ",".join(f'{k}="{_escape_label(v)}"' for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def counter_inc(name: str, value: float = 1.0, *, labels: Optional[Dict[str, str]] = None) -> None:
    key = _metric_key(name, labels)
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + value
        _counter_types[name] = "counter"


def gauge_set(name: str, value: float, *, labels: Optional[Dict[str, str]] = None) -> None:
    key = _metric_key(name, labels)
    with _lock:
        _gauges[key] = float(value)
        _gauge_types[name] = "gauge"


def normalize_path(path: str) -> str:
    """Collapse high-cardinality paths for HTTP metrics."""
    p = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    if p == "/health" or p == "/metrics":
        return p
    if p.startswith("/v1/auth/"):
        return "/v1/auth/*"
    if p.startswith("/v1/sessions/"):
        return "/v1/sessions/*"
    if p.startswith("/v1/runs/"):
        return "/v1/runs/*"
    if p.startswith("/v1/legal/"):
        return "/v1/legal/*"
    if p.startswith("/v1/admin/"):
        return "/v1/admin/*"
    return p


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        emitted_types: set[str] = set()
        for key in sorted(_counters.keys()):
            base = re.split(r"[{]", key, maxsplit=1)[0]
            type_key = f"counter:{base}"
            if type_key not in emitted_types:
                lines.append(f"# TYPE {base} counter")
                emitted_types.add(type_key)
            lines.append(f"{key} {_counters[key]}")
        for key in sorted(_gauges.keys()):
            base = re.split(r"[{]", key, maxsplit=1)[0]
            type_key = f"gauge:{base}"
            if type_key not in emitted_types:
                lines.append(f"# TYPE {base} gauge")
                emitted_types.add(type_key)
            lines.append(f"{key} {_gauges[key]}")
    return "\n".join(lines) + ("\n" if lines else "")


def snapshot() -> Tuple[Dict[str, float], Dict[str, float]]:
    with _lock:
        return dict(_counters), dict(_gauges)
