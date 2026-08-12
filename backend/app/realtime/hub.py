"""Bounded unauthenticated WebSocket fan-out for public spectators."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.metrics import WEBSOCKET_CONNECTIONS
from app.ratelimit import RateLimitExceeded, check_rate_limit, register_limit
from app.realtime.channels import channels_exist, normalize_channel
from app.realtime.fanout import Subscription, fanout

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 16
MAX_CONTROL_FRAME_BYTES = 4096
MAX_CONTROL_FRAMES_PER_MINUTE = 120
_OUTBOUND_QUEUE_SIZE = 128

register_limit("ws_connect", max_count=60, window_s=60)


async def _writer(websocket: WebSocket, outbound: asyncio.Queue[str]) -> None:
    while True:
        await websocket.send_text(await outbound.get())


def _enqueue(outbound: asyncio.Queue[str], payload: str) -> None:
    if outbound.full():
        with suppress(asyncio.QueueEmpty):
            outbound.get_nowait()
    with suppress(asyncio.QueueFull):
        outbound.put_nowait(payload)


async def _relay(subscription: Subscription, outbound: asyncio.Queue[str]) -> None:
    while True:
        _enqueue(outbound, await subscription.queue.get())


async def _control_loop(
    websocket: WebSocket,
    subscription: Subscription,
    outbound: asyncio.Queue[str],
) -> None:
    frame_times: deque[float] = deque()
    desired: set[str] = set()
    while True:
        raw = await websocket.receive_text()
        if len(raw.encode("utf-8")) > MAX_CONTROL_FRAME_BYTES:
            await websocket.close(code=1009, reason="control frame too large")
            return

        now = time.monotonic()
        while frame_times and frame_times[0] <= now - 60:
            frame_times.popleft()
        if len(frame_times) >= MAX_CONTROL_FRAMES_PER_MINUTE:
            await websocket.close(code=1008, reason="control frame rate exceeded")
            return
        frame_times.append(now)

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        frame_type = data.get("type")
        if frame_type == "ping":
            _enqueue(outbound, '{"type":"pong"}')
            continue
        if frame_type not in {"subscribe", "unsubscribe"}:
            continue

        values = data.get("channels")
        if not isinstance(values, list) or len(values) > MAX_SUBSCRIPTIONS:
            _enqueue(outbound, '{"type":"error","code":"invalid_channels"}')
            continue
        channels = {channel for value in values if (channel := normalize_channel(value))}
        if len(channels) != len(values):
            _enqueue(outbound, '{"type":"error","code":"invalid_channel"}')
            continue
        try:
            known_channels = await channels_exist(channels)
        except SQLAlchemyError:
            logger.exception("failed to validate realtime channels")
            _enqueue(outbound, '{"type":"error","code":"realtime_unavailable"}')
            continue
        if not known_channels:
            _enqueue(outbound, '{"type":"error","code":"channel_not_found"}')
            continue

        if frame_type == "subscribe":
            if len(desired | channels) > MAX_SUBSCRIPTIONS:
                _enqueue(outbound, '{"type":"error","code":"too_many_channels"}')
                continue
            desired.update(channels)
        else:
            desired.difference_update(channels)
        await fanout.replace_channels(subscription, desired)


async def serve(websocket: WebSocket) -> None:
    """Relay allowlisted public channels using bounded per-client resources."""
    client_identity = websocket.client.host if websocket.client else "unknown"
    if get_settings().trust_forwarded_client_ip:
        forwarded = websocket.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            client_identity = forwarded
    try:
        await check_rate_limit("ws_connect", client_identity)
    except RateLimitExceeded as exc:
        await websocket.close(code=1013, reason=f"retry after {exc.retry_after}s")
        return

    await websocket.accept()
    subscription = await fanout.register()
    outbound: asyncio.Queue[str] = asyncio.Queue(maxsize=_OUTBOUND_QUEUE_SIZE)
    writer = asyncio.create_task(_writer(websocket, outbound), name="websocket-writer")
    relay = asyncio.create_task(_relay(subscription, outbound), name="websocket-relay")
    WEBSOCKET_CONNECTIONS.inc()
    try:
        await _control_loop(websocket, subscription, outbound)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("unexpected WebSocket control failure")
    finally:
        WEBSOCKET_CONNECTIONS.dec()
        await fanout.unregister(subscription)
        for task in (relay, writer):
            task.cancel()
        await asyncio.gather(relay, writer, return_exceptions=True)
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close()
