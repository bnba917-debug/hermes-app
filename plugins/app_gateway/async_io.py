"""Run blocking callables off the FastAPI event loop."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Execute *func* in a worker thread (Python 3.9+ ``asyncio.to_thread``)."""
    if kwargs:
        return await asyncio.to_thread(lambda: func(*args, **kwargs))
    if args:
        return await asyncio.to_thread(func, *args)
    return await asyncio.to_thread(func)
