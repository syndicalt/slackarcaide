"""Failure-mode tests for bounded realtime and durable social behavior."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app import ratelimit
from app.api import ws
from app.db import get_sessionmaker, init_db
from app.models import Agent, Match, Message, Reaction
from app.realtime import hub, publisher
from app.realtime.channels import channels_exist, normalize_channel
from app.realtime.fanout import RedisFanout, Subscription
from app.services import messaging


@pytest.fixture
async def session():
    await init_db()
    async with get_sessionmaker()() as value:
        yield value
        await value.rollback()


async def _agent(session, prefix: str) -> Agent:
    suffix = uuid.uuid4().hex
    agent = Agent(
        display_name=f"{prefix}-{suffix[:8]}",
        api_key_hash=f"hash-{suffix}",
        stats={},
    )
    session.add(agent)
    await session.commit()
    return agent


async def _match(session, author: Agent) -> Match:
    match = Match(
        game_type="chess",
        mode="turnbased",
        status="lobby",
        config={},
        players=[{"agent_id": str(author.id), "seat": 0}],
    )
    session.add(match)
    await session.commit()
    return match


def test_public_channel_namespace_is_canonical_and_bounded():
    identifier = uuid.uuid4()
    assert normalize_channel("lobby") == "lobby"
    assert normalize_channel("messages:global") == "messages:global"
    assert normalize_channel(f"match:{identifier}") == f"match:{identifier}"
    assert normalize_channel(f"messages:{str(identifier).upper()}") == (f"messages:{identifier}")
    assert normalize_channel("messages:arbitrary") is None
    assert normalize_channel("other:global") is None
    assert normalize_channel("x" * 81) is None


async def test_realtime_channels_must_reference_a_durable_match(session):
    author = await _agent(session, "channel")
    match = await _match(session, author)
    assert await channels_exist({"lobby", "messages:global"}) is True
    assert await channels_exist({f"match:{match.id}", f"messages:{match.id}"}) is True
    assert await channels_exist({f"match:{uuid.uuid4()}"}) is False


async def test_message_parent_and_channel_invariants(session, monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return True

    monkeypatch.setattr(messaging, "publish", no_publish)
    author = await _agent(session, "social")
    match = await _match(session, author)

    with pytest.raises(ValueError, match="channel_not_found"):
        await messaging.post_message(
            session,
            channel=str(uuid.uuid4()),
            author_id=author.id,
            content="hello",
        )

    root = await messaging.post_message(
        session,
        channel=str(match.id),
        author_id=author.id,
        content="root",
    )
    with pytest.raises(ValueError, match="parent_channel_mismatch"):
        await messaging.post_message(
            session,
            channel="global",
            author_id=author.id,
            content="wrong channel",
            parent_id=root.id,
        )
    reply = await messaging.post_message(
        session,
        channel=str(match.id),
        author_id=author.id,
        content="reply",
        parent_id=root.id,
    )
    with pytest.raises(ValueError, match="nested_reply_not_allowed"):
        await messaging.post_message(
            session,
            channel=str(match.id),
            author_id=author.id,
            content="nested",
            parent_id=reply.id,
        )


async def test_cursor_is_stable_when_timestamps_are_equal(session):
    author = await _agent(session, "cursor")
    match = await _match(session, author)
    channel = str(match.id)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    identifiers = sorted((uuid.uuid4(), uuid.uuid4(), uuid.uuid4()), reverse=True)
    session.add_all(
        [
            Message(
                id=identifier,
                channel=channel,
                author_id=author.id,
                content=str(index),
                created_at=created,
            )
            for index, identifier in enumerate(identifiers)
        ]
    )
    await session.commit()

    first = await messaging.list_messages(session, channel, limit=2)
    assert [message.id for message in first] == identifiers[:2]
    cursor = messaging.decode_cursor(messaging.encode_cursor(first[-1]))
    second = await messaging.list_messages(session, channel, limit=2, before=cursor)
    assert [message.id for message in second] == identifiers[2:]
    with pytest.raises(ValueError, match="invalid_cursor"):
        messaging.decode_cursor("not-base64!")


async def test_one_reaction_per_author_is_race_safe(session, monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return True

    monkeypatch.setattr(messaging, "publish", no_publish)
    author = await _agent(session, "react")
    message = await messaging.post_message(
        session, channel="global", author_id=author.id, content="react here"
    )
    message_id = message.id
    author_id = author.id
    assert await messaging.add_reaction(session, message, author_id, "👍") is True
    assert await messaging.add_reaction(session, message, author_id, "👎") is False
    rows = (
        await session.scalars(
            select(Reaction).where(
                Reaction.message_id == message_id,
                Reaction.author_id == author_id,
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].emoji == "👍"


async def test_batched_details_return_reactions_counts_and_quotes(session, monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return True

    monkeypatch.setattr(messaging, "publish", no_publish)
    author = await _agent(session, "batch")
    root = await messaging.post_message(
        session, channel="global", author_id=author.id, content=f"hi @{author.id}"
    )
    reply = await messaging.post_message(
        session,
        channel="global",
        author_id=author.id,
        content="reply",
        parent_id=root.id,
    )
    assert await messaging.add_reaction(session, root, author.id, "✅")

    root_detail, reply_detail = await messaging.message_details(session, [root, reply])
    assert root_detail["reply_count"] == 1
    assert root_detail["mentions"] == [str(author.id)]
    assert root_detail["reactions"]["✅"]["count"] == 1
    assert reply_detail["quote"]["id"] == str(root.id)


async def test_fanout_reuses_one_task_and_bounds_slow_client_queue(monkeypatch):
    started = 0
    stop = asyncio.Event()

    async def inert_run(_self):
        nonlocal started
        started += 1
        await stop.wait()

    monkeypatch.setattr(RedisFanout, "_run", inert_run)
    multiplexer = RedisFanout()
    first = await multiplexer.register()
    second = await multiplexer.register()
    await asyncio.sleep(0)
    assert started == 1
    assert multiplexer._task is not None

    await multiplexer.replace_channels(first, {"lobby"})
    await multiplexer.replace_channels(second, {"lobby"})
    for index in range(150):
        await multiplexer._deliver("lobby", str(index))
    assert first.queue.qsize() == 128
    assert await first.queue.get() == "22"
    assert second.queue.qsize() == 128
    await multiplexer.close()


async def test_fanout_does_not_lose_first_subscription_wakeup(monkeypatch):
    class FakePubsub:
        subscribed: set[str] = set()

        async def subscribe(self, *channels):
            self.subscribed.update(channels)

        async def unsubscribe(self, *channels):
            self.subscribed.difference_update(channels)

        async def get_message(self, **_kwargs):
            await asyncio.sleep(0.01)
            return None

        async def aclose(self):
            return None

    pubsub = FakePubsub()

    class FakeRedis:
        def pubsub(self):
            return pubsub

    async def fake_redis():
        return FakeRedis()

    monkeypatch.setattr("app.realtime.fanout.get_redis", fake_redis)
    multiplexer = RedisFanout()
    subscription = await multiplexer.register()
    await asyncio.sleep(0)
    await multiplexer.replace_channels(subscription, {"lobby"})
    for _ in range(20):
        if "lobby" in pubsub.subscribed:
            break
        await asyncio.sleep(0.01)
    assert pubsub.subscribed == {"lobby"}
    await multiplexer.close()


def test_websocket_rejects_invalid_channels_and_serializes_pong(monkeypatch):
    class StubFanout:
        def __init__(self):
            self.channels: set[str] = set()

        async def register(self):
            return Subscription()

        async def replace_channels(self, subscription, channels):
            subscription.channels = set(channels)
            self.channels = set(channels)

        async def unregister(self, subscription):
            subscription.channels.clear()

    async def permit(*_args):
        return None

    stub = StubFanout()
    monkeypatch.setattr(hub, "fanout", stub)
    monkeypatch.setattr(hub, "check_rate_limit", permit)
    app = FastAPI()
    app.include_router(ws.router)

    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "subscribe", "channels": ["messages:anything"]})
        assert socket.receive_json() == {"type": "error", "code": "invalid_channel"}
        socket.send_json({"type": "subscribe", "channels": ["lobby"]})
        socket.send_json({"type": "ping"})
        assert socket.receive_json() == {"type": "pong"}
        assert stub.channels == {"lobby"}


def test_websocket_closes_oversized_control_frame(monkeypatch):
    async def permit(*_args):
        return None

    monkeypatch.setattr(hub, "check_rate_limit", permit)
    app = FastAPI()
    app.include_router(ws.router)
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/ws") as socket,
    ):
        socket.send_text("x" * (hub.MAX_CONTROL_FRAME_BYTES + 1))
        socket.receive_text()
        assert closed.value.code == 1009


async def test_publish_circuit_skips_repeated_redis_failures(monkeypatch):
    calls = 0

    async def unavailable():
        nonlocal calls
        calls += 1
        raise ConnectionError("redis down")

    monkeypatch.setattr(publisher, "get_redis", unavailable)
    monkeypatch.setattr(publisher, "_failures", 0)
    monkeypatch.setattr(publisher, "_retry_at", 0.0)
    monkeypatch.setattr(publisher, "_next_log_at", float("inf"))
    assert await publisher.publish("lobby", {"status": "running"}) is False
    assert await publisher.publish("lobby", {"status": "running"}) is False
    assert calls == 1


async def test_rate_limit_uses_shared_redis_counter(monkeypatch):
    class FakeRedis:
        count = 0

        async def eval(self, _script, number_of_keys, key, window_ms):
            assert number_of_keys == 1
            assert key.startswith("slackarcaide:rate:test_shared:")
            assert window_ms == 60_000
            self.count += 1
            return [self.count, 60_000]

    redis = FakeRedis()

    async def fake_redis():
        return redis

    ratelimit.register_limit("test_shared", 2, 60)
    monkeypatch.setattr(ratelimit, "get_redis", fake_redis)
    monkeypatch.setattr(ratelimit, "_redis_retry_at", 0.0)
    await ratelimit.check_rate_limit("test_shared", "spectator")
    await ratelimit.check_rate_limit("test_shared", "spectator")
    with pytest.raises(ratelimit.RateLimitExceeded) as caught:
        await ratelimit.check_rate_limit("test_shared", "spectator")
    assert caught.value.retry_after == 60


async def test_rate_limit_fallback_is_bounded_and_enforced(monkeypatch):
    async def unavailable():
        raise ConnectionError("redis down")

    ratelimit.register_limit("test_fallback", 1, 60)
    monkeypatch.setattr(ratelimit, "get_redis", unavailable)
    monkeypatch.setattr(ratelimit, "_redis_retry_at", 0.0)
    monkeypatch.setattr(ratelimit, "_next_log_at", float("inf"))
    ratelimit._fallback.clear()
    await ratelimit.check_rate_limit("test_fallback", "agent")
    with pytest.raises(ratelimit.RateLimitExceeded):
        await ratelimit.check_rate_limit("test_fallback", "agent")
    assert len(ratelimit._fallback) == 1
