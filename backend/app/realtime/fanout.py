"""Process-level Redis subscription multiplexer for WebSocket spectators.

Each backend process owns one Redis PubSub connection regardless of its socket
count. Client queues are bounded and favor the newest event when a slow client
falls behind; REST remains the durable reconciliation path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field

from app.redis import get_redis

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 0.5
_MAX_RETRY_SECONDS = 15.0
_CLIENT_QUEUE_SIZE = 128


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[str] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
    )
    channels: set[str] = field(default_factory=set)


class RedisFanout:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[Subscription]] = {}
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._next_log_at = 0.0

    async def register(self) -> Subscription:
        subscription = Subscription()
        async with self._lock:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="redis-realtime-fanout")
        return subscription

    async def replace_channels(self, subscription: Subscription, channels: set[str]) -> None:
        async with self._lock:
            removed = subscription.channels - channels
            added = channels - subscription.channels
            for channel in removed:
                listeners = self._subscribers.get(channel)
                if listeners is not None:
                    listeners.discard(subscription)
                    if not listeners:
                        self._subscribers.pop(channel, None)
            for channel in added:
                self._subscribers.setdefault(channel, set()).add(subscription)
            subscription.channels = set(channels)
            if removed or added:
                self._changed.set()

    async def unregister(self, subscription: Subscription) -> None:
        await self.replace_channels(subscription, set())

    async def close(self) -> None:
        async with self._lock:
            task = self._task
            self._task = None
            self._subscribers.clear()
            self._changed.set()
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _desired_channels(self) -> set[str]:
        async with self._lock:
            return set(self._subscribers)

    async def _deliver(self, channel: str, data: str) -> None:
        async with self._lock:
            listeners = tuple(self._subscribers.get(channel, ()))
        for subscription in listeners:
            if subscription.queue.full():
                with suppress(asyncio.QueueEmpty):
                    subscription.queue.get_nowait()
            with suppress(asyncio.QueueFull):
                subscription.queue.put_nowait(data)

    async def _run(self) -> None:
        retry_seconds = 0.5
        while True:
            pubsub = None
            actual: set[str] = set()
            try:
                redis = await get_redis()
                pubsub = redis.pubsub()
                while True:
                    # Clear before snapshotting. A concurrent update either lands
                    # in the snapshot or sets the event after this point; clearing
                    # after the snapshot can lose the wake-up when actual is empty.
                    self._changed.clear()
                    desired = await self._desired_channels()
                    remove = actual - desired
                    add = desired - actual
                    if remove:
                        await pubsub.unsubscribe(*remove)
                    if add:
                        await pubsub.subscribe(*add)
                    actual = desired
                    if not actual:
                        await self._changed.wait()
                        continue

                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=_READ_TIMEOUT
                    )
                    if message and message.get("type") == "message":
                        channel = message.get("channel")
                        data = message.get("data")
                        if isinstance(channel, str) and isinstance(data, str):
                            await self._deliver(channel, data)
                    retry_seconds = 0.5
            except asyncio.CancelledError:
                raise
            except Exception:
                now = time.monotonic()
                if now >= self._next_log_at:
                    logger.warning(
                        "Redis realtime subscription unavailable; retrying",
                        exc_info=True,
                    )
                    self._next_log_at = now + 30.0
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._changed.wait(), timeout=retry_seconds)
                retry_seconds = min(retry_seconds * 2, _MAX_RETRY_SECONDS)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        logger.debug("failed to close Redis PubSub", exc_info=True)


fanout = RedisFanout()


async def close_fanout() -> None:
    await fanout.close()
