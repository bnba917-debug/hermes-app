"""Bounded agent concurrency for single-process multi-user gateways."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class ConcurrencyStats:
    max_concurrent: int
    active: int
    waiting: int
    total_started: int
    total_rejected: int


class AgentConcurrencyPool:
    """Limits in-flight agent runs and uses a dedicated thread pool."""

    def __init__(
        self,
        *,
        max_concurrent: int = 64,
        max_workers: int = 96,
        queue_timeout_seconds: float = 300.0,
    ) -> None:
        self._max_concurrent = max(1, int(max_concurrent))
        self._queue_timeout = max(1.0, float(queue_timeout_seconds))
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._waiting = 0
        self._active = 0
        self._lock = threading.Lock()
        self._total_started = 0
        self._total_rejected = 0
        self._executor = ThreadPoolExecutor(
            max_workers=max(4, int(max_workers)),
            thread_name_prefix="app-gw-agent",
        )

    @property
    def executor(self) -> ThreadPoolExecutor:
        return self._executor

    def stats(self) -> ConcurrencyStats:
        with self._lock:
            return ConcurrencyStats(
                max_concurrent=self._max_concurrent,
                active=self._active,
                waiting=self._waiting,
                total_started=self._total_started,
                total_rejected=self._total_rejected,
            )

    async def run(
        self,
        fn: Callable[[], T],
        *,
        user_id: str = "",
    ) -> T:
        """Run *fn* in the thread pool after acquiring a concurrency slot."""
        loop = asyncio.get_running_loop()
        acquired = False
        deadline = time.monotonic() + self._queue_timeout

        with self._lock:
            self._waiting += 1
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        self._semaphore.acquire(),
                        timeout=max(0.05, deadline - time.monotonic()),
                    )
                    acquired = True
                    break
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline:
                        with self._lock:
                            self._total_rejected += 1
                        raise AgentQueueTimeout(
                            f"Server busy ({self._max_concurrent} agents active); "
                            f"try again later (user={user_id or '?'})"
                        )
        finally:
            with self._lock:
                self._waiting = max(0, self._waiting - 1)

        with self._lock:
            self._active += 1
            self._total_started += 1
        try:
            ctx = copy_context()
            return await loop.run_in_executor(self._executor, ctx.run, fn)
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)
            if acquired:
                self._semaphore.release()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class AgentQueueTimeout(Exception):
    """Raised when no agent slot is available within the queue timeout."""
