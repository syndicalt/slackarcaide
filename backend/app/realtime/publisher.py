"""Redis pub/sub transport helper.

Engine/services publish structured JSON to a channel; the WS hub (realtime/hub.py)
subscribes and fans out to connected clients. Redis is transport only — the engine
holds authoritative state.
"""
import json
import logging

from app.redis import get_redis

logger = logging.getLogger(__name__)


async def publish(channel: str, payload: dict) -> None:
    """Best-effort fan-out. Redis is transport only; a connection failure here
    must never break authoritative engine/service writes, so we log and move on."""
    try:
        r = await get_redis()
        await r.publish(channel, json.dumps(payload, default=str))
    except Exception:
        logger.warning("realtime publish skipped (Redis unavailable)", exc_info=True)
