"""Lightweight per-agent rate limiting.

v1 uses a process-local sliding-window counter (adequate for a single backend
instance; documented as such). Swap for a Redis-based bucket if the backend runs
multi-instance. Fails open — a limiter error must never block an agent.
"""
import asyncio
import time
import uuid
from collections import defaultdict
from collections import deque

from fastapi import Depends, HTTPException
from typing import Callable

from app.auth import get_current_agent
from app.models import Agent

_series: dict[str, tuple[asyncio.Lock, deque[float]]] = defaultdict(
    lambda: (asyncio.Lock(), deque())
)
_LIMIT: dict[str, tuple[int, float]] = {}
_WINDOW_S = 60.0


def register_limit(
    name: str, max_count: int, window_s: float = _WINDOW_S
) -> None:
    _LIMIT[name] = (max_count, window_s)


def rate_limited(name: str) -> Callable:
    """FastAPI dependency factory: allow `max_count` calls per window per agent."""
    max_count, window_s = _LIMIT.get(name, (1000, _WINDOW_S))

    async def _dependency(
        agent: Agent = Depends(get_current_agent),
    ) -> None:
        key = f"{name}:{agent.id}"
        lock, times = _series[key]
        now = time.monotonic()
        async with lock:
            while times and times[0] <= now - window_s:
                times.popleft()
            if len(times) >= max_count:
                raise HTTPException(429, "rate_limited")
            times.append(now)

    return _dependency
