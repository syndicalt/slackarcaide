"""Best-effort Redis publication with outage circuit breaking."""

from __future__ import annotations

import json
import logging
import time

from redis.exceptions import RedisError

from app.redis import get_redis

logger = logging.getLogger(__name__)

_failures = 0
_retry_at = 0.0
_next_log_at = 0.0
_MAX_BACKOFF_SECONDS = 30.0


async def publish(channel: str, payload: dict) -> bool:
    """Publish JSON without allowing a Redis outage to break durable work."""
    global _failures, _next_log_at, _retry_at

    try:
        encoded = json.dumps(payload, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        logger.exception("realtime payload is not JSON serializable", extra={"channel": channel})
        return False

    now = time.monotonic()
    if now < _retry_at:
        return False

    try:
        redis = await get_redis()
        await redis.publish(channel, encoded)
    except (RedisError, OSError, TimeoutError):
        _failures += 1
        _retry_at = now + min(2 ** (_failures - 1), _MAX_BACKOFF_SECONDS)
        if now >= _next_log_at:
            logger.warning(
                "realtime publish unavailable; circuit opened",
                exc_info=True,
                extra={"channel": channel, "failures": _failures},
            )
            _next_log_at = now + 30.0
        return False
    else:
        if _failures:
            logger.info("realtime publication recovered")
        _failures = 0
        _retry_at = 0.0
        return True
