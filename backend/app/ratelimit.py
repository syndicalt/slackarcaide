"""Redis-backed rate limits with a bounded process-local outage fallback."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

from app.auth import get_current_agent
from app.config import get_settings
from app.models import Agent
from app.redis import get_redis

logger = logging.getLogger(__name__)

_LIMIT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LIMITS: dict[str, tuple[int, float]] = {}
_fallback: OrderedDict[str, deque[float]] = OrderedDict()
_fallback_lock = asyncio.Lock()
_MAX_FALLBACK_IDENTITIES = 10_000
_redis_retry_at = 0.0
_next_log_at = 0.0

_FIXED_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('PTTL', KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    retry_after: int


def register_limit(name: str, max_count: int, window_s: float = 60.0) -> None:
    if not _LIMIT_NAME.fullmatch(name):
        raise ValueError("invalid rate-limit name")
    if max_count < 1 or window_s <= 0:
        raise ValueError("rate-limit values must be positive")
    _LIMITS[name] = (max_count, window_s)


def _redis_key(name: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:32]
    return f"slackarcaide:rate:{name}:{digest}"


async def _check_fallback(name: str, identity: str, max_count: int, window_s: float) -> None:
    key = _redis_key(name, identity)
    now = time.monotonic()
    async with _fallback_lock:
        timestamps = _fallback.setdefault(key, deque())
        _fallback.move_to_end(key)
        while timestamps and timestamps[0] <= now - window_s:
            timestamps.popleft()
        if len(timestamps) >= max_count:
            raise RateLimitExceeded(max(1, math.ceil(timestamps[0] + window_s - now)))
        timestamps.append(now)
        while len(_fallback) > _MAX_FALLBACK_IDENTITIES:
            _fallback.popitem(last=False)


async def check_rate_limit(name: str, identity: str) -> None:
    """Consume one request from a named shared limit."""
    global _next_log_at, _redis_retry_at

    try:
        max_count, window_s = _LIMITS[name]
    except KeyError as exc:
        raise RuntimeError(f"unregistered rate limit: {name}") from exc

    now = time.monotonic()
    if now >= _redis_retry_at:
        try:
            redis = await get_redis()
            count, ttl_ms = await redis.eval(
                _FIXED_WINDOW_SCRIPT,
                1,
                _redis_key(name, identity),
                max(1, math.ceil(window_s * 1000)),
            )
            if int(count) > max_count:
                raise RateLimitExceeded(max(1, math.ceil(int(ttl_ms) / 1000)))
            return
        except RateLimitExceeded:
            raise
        except asyncio.CancelledError:
            raise
        except (RedisError, OSError, TimeoutError, ValueError):
            _redis_retry_at = now + 5.0
            if now >= _next_log_at:
                logger.warning(
                    "Redis rate limiter unavailable; using local fallback",
                    exc_info=True,
                )
                _next_log_at = now + 30.0
    await _check_fallback(name, identity, max_count, window_s)


def _http_limit(exc: RateLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="rate_limited",
        headers={"Retry-After": str(exc.retry_after)},
    )


def rate_limited(name: str) -> Callable:
    """FastAPI dependency applying a named limit to the authenticated agent."""
    if name not in _LIMITS:
        raise RuntimeError(f"unregistered rate limit: {name}")

    async def dependency(agent: Agent = Depends(get_current_agent)) -> None:
        try:
            await check_rate_limit(name, str(agent.id))
        except RateLimitExceeded as exc:
            raise _http_limit(exc) from exc

    return dependency


def client_rate_limited(name: str) -> Callable:
    """Apply a limit to the direct peer, or trusted ingress forwarded address."""
    if name not in _LIMITS:
        raise RuntimeError(f"unregistered rate limit: {name}")

    async def dependency(request: Request) -> None:
        identity = request.client.host if request.client else "unknown"
        if get_settings().trust_forwarded_client_ip:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                identity = forwarded
        try:
            await check_rate_limit(name, identity)
        except RateLimitExceeded as exc:
            raise _http_limit(exc) from exc

    return dependency
