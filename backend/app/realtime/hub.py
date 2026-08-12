"""WebSocket fan-out hub backed by Redis pub/sub.

Clients connect over WS and send JSON control frames to subscribe/unsubscribe
from literal Redis channel names (``match:{id}``, ``messages:{channel}``).
Every message published to a subscribed channel is forwarded to the socket
verbatim (the backend publishes JSON text via realtime/publisher.py).

The hub is resilient to Redis being temporarily unavailable: subscribe/read
failures are logged, the socket stays open, and a renewed subscription is
attempted on the next control frame or read cycle.
"""
import asyncio
import json
import logging

from fastapi import WebSocket

from app.redis import get_redis

logger = logging.getLogger("app.realtime.hub")

_READ_TIMEOUT = 1.0


async def _reader(
    websocket: WebSocket,
    subscribed: set[str],
    stop: asyncio.Event,
) -> None:
    """Own the Redis pubsub subscription and fan messages out to the socket.

    ``subscribed`` is the live, shared desired-set mutated by the control loop.
    It is re-snapshotted each cycle and the Redis subscription is rebuilt to
    match, so a Redis outage only delays the effect until the next message or
    read timeout.
    """
    pubsub = None
    actual: set[str] = set()
    try:
        while not stop.is_set():
            desired = set(subscribed)
            try:
                if pubsub is None:
                    r = await get_redis()
                    pubsub = r.pubsub()
                    actual = set()

                to_add = desired - actual
                to_remove = actual - desired
                if to_remove:
                    await pubsub.unsubscribe(*to_remove)
                if to_add:
                    await pubsub.subscribe(*to_add)
                actual = set(desired)

                if not actual:
                    # nothing to listen to yet; idle so we don't busy-spin
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=_READ_TIMEOUT)
                    except asyncio.TimeoutError:
                        pass
                    continue

                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_READ_TIMEOUT
                )
                if msg and msg.get("type") == "message":
                    data = msg.get("data")
                    if isinstance(data, str):
                        await websocket.send_text(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime subscribe/read failed", exc_info=True)
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass
                pubsub = None
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_READ_TIMEOUT)
                except asyncio.TimeoutError:
                    pass
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("realtime reader stopped unexpectedly")
    finally:
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception:
                pass


async def _control_loop(websocket: WebSocket, subscribed: set[str]) -> None:
    """Read client control frames and mutate the desired subscription set."""
    while True:
        raw = await websocket.receive_text()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        ctype = data.get("type")
        if ctype == "subscribe":
            channels = data.get("channels")
            if isinstance(channels, list):
                subscribed.update(c for c in channels if isinstance(c, str))
        elif ctype == "unsubscribe":
            channels = data.get("channels")
            if isinstance(channels, list):
                subscribed.difference_update(c for c in channels if isinstance(c, str))
        elif ctype == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))


async def serve(websocket: WebSocket) -> None:
    """Accept a socket and relay subscribed Redis channels until disconnect."""
    await websocket.accept()

    subscribed: set[str] = set()
    stop = asyncio.Event()
    reader: asyncio.Task | None = None
    try:
        reader = asyncio.create_task(_reader(websocket, subscribed, stop))
        await _control_loop(websocket, subscribed)
    except Exception:
        # covers WebSocketDisconnect and ordinary socket teardown
        pass
    finally:
        stop.set()
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await websocket.close()
        except Exception:
            pass
